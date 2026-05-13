"""
AI Evaluation Engine
====================
Production-safe evaluation pipeline:
- Gibberish / low-quality answer detection (no API call wasted)
- Groq API with 3-attempt retry + exponential backoff
- 3-strategy JSON extraction (handles markdown fences, prose wrappers)
- Heuristic partial evaluation when API is completely unavailable
- Never raises, never returns a generic "Fallback evaluation." string
- Safe to import even when GROQ_API_KEY is not set
"""

import json
import logging
import math
import os
import re
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("interviews.evaluator")

# ---------------------------------------------------------------------------
# Groq client — imported lazily so a missing package never crashes startup
# ---------------------------------------------------------------------------

def _build_groq_client():
    # type: () -> Optional[object]
    """
    Returns a Groq client if the package is installed and the key is set.
    Returns None otherwise — the app will still boot and serve pages.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        logger.warning(
            "GROQ_API_KEY is not set. "
            "AI evaluation will use heuristic scoring until the key is added."
        )
        return None
    try:
        from groq import Groq  # type: ignore
        return Groq(api_key=key)
    except ImportError:
        logger.error("groq package is not installed. Check requirements.txt.")
        return None
    except Exception as exc:
        logger.error("Failed to initialise Groq client: %s", exc)
        return None


# Module-level client — built once at import time.
# Re-checked on every evaluate_answer() call so a key added after startup works.
_groq_client = _build_groq_client()

# ---------------------------------------------------------------------------
# Gibberish / low-quality detection
# ---------------------------------------------------------------------------

def _is_low_quality(answer):
    # type: (str) -> Tuple[bool, str]
    """Returns (is_low_quality, reason)."""
    stripped = answer.strip()

    if not stripped:
        return True, "empty"

    if len(stripped) < 10:
        return True, "too_short"

    # Gibberish: less than 35% alphabetic characters
    alpha_count = sum(1 for c in stripped if c.isalpha())
    if len(stripped) > 5 and (alpha_count / len(stripped)) < 0.35:
        return True, "gibberish"

    # Too few words
    if len(stripped.split()) < 3:
        return True, "too_short"

    return False, ""


def _low_quality_result(reason, question):
    # type: (str, str) -> Dict
    messages = {
        "empty":     "No answer was provided.",
        "too_short": "The answer is too brief to evaluate meaningfully.",
        "gibberish": (
            "The answer appears to be random keyboard input "
            "and does not address the question."
        ),
    }
    feedback = messages.get(reason, "The answer could not be evaluated.")
    return {
        "technical_score":     0,
        "communication_score": 0,
        "confidence_score":    0,
        "answer_quality":      "No Answer",
        "strengths":           [],
        "weaknesses":          [feedback],
        "improvement_tips": [
            "Please provide a genuine answer to: '{}'".format(question),
            "Aim for at least 2-3 sentences covering the core concept.",
        ],
        "follow_up_questions": [],
        "overall_score":       0,
        "feedback":            feedback,
    }

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a strict senior technical interviewer at a FAANG-level company.\n"
    "Evaluate the candidate's answer and return ONLY valid JSON — no markdown, no prose.\n\n"
    "JSON schema (all fields required):\n"
    "{\n"
    '  "technical_score":      <integer 0-40>,\n'
    '  "communication_score":  <integer 0-30>,\n'
    '  "confidence_score":     <integer 0-30>,\n'
    '  "answer_quality":       <"Excellent"|"Good"|"Average"|"Poor"|"No Answer">,\n'
    '  "strengths":            [<string>, ...],\n'
    '  "weaknesses":           [<string>, ...],\n'
    '  "improvement_tips":     [<string>, ...],\n'
    '  "follow_up_questions":  [<string>, ...]\n'
    "}\n\n"
    "Scoring rules:\n"
    "- technical_score:     depth, accuracy, completeness (0-40)\n"
    "- communication_score: clarity, structure, conciseness (0-30)\n"
    "- confidence_score:    specificity, examples, assertiveness (0-30)\n"
    "Be strict. Vague or single-sentence answers score 0-15 total.\n"
    "Solid, detailed answers score 70-100 total."
)


def _user_prompt(role, question, answer):
    # type: (str, str, str) -> str
    return (
        "Role: {}\n\n"
        "Question: {}\n\n"
        "Candidate Answer: {}\n\n"
        "Return the JSON evaluation now."
    ).format(role, question, answer)

# ---------------------------------------------------------------------------
# JSON extraction — 3 strategies
# ---------------------------------------------------------------------------

def _extract_json(text):
    # type: (str) -> Optional[Dict]
    # Strategy 1: direct parse
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: find first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: strip markdown code fences then parse
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning("JSON extraction failed. Raw snippet: %s", text[:300])
    return None

# ---------------------------------------------------------------------------
# Groq API call with retry + exponential backoff
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY  = 1.5  # seconds


def _call_groq(client, role, question, answer):
    # type: (object, str, str, str) -> Optional[Dict]
    prompt = _user_prompt(role, question, answer)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("Groq API call — attempt %d/%d", attempt, _MAX_RETRIES)

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.3,
                max_tokens=800,
            )

            raw = response.choices[0].message.content
            logger.debug("Raw AI response: %s", raw[:400])

            parsed = _extract_json(raw)
            if parsed is not None:
                return parsed

            logger.warning("Attempt %d: JSON parse failed.", attempt)

        except Exception as exc:
            logger.error("Groq error on attempt %d: %s", attempt, exc)

        if attempt < _MAX_RETRIES:
            delay = _BASE_DELAY * math.pow(2, attempt - 1)
            logger.info("Retrying in %.1fs...", delay)
            time.sleep(delay)

    return None

# ---------------------------------------------------------------------------
# Score normalisation
# ---------------------------------------------------------------------------

def _normalise(data):
    # type: (Dict) -> Dict
    def clamp(val, lo, hi, default):
        try:
            return max(lo, min(hi, int(val)))
        except (TypeError, ValueError):
            return default

    data["technical_score"]     = clamp(data.get("technical_score"),     0, 40, 0)
    data["communication_score"] = clamp(data.get("communication_score"), 0, 30, 0)
    data["confidence_score"]    = clamp(data.get("confidence_score"),    0, 30, 0)

    valid = {"Excellent", "Good", "Average", "Poor", "No Answer"}
    if data.get("answer_quality") not in valid:
        data["answer_quality"] = "Average"

    for field in ("strengths", "weaknesses", "improvement_tips", "follow_up_questions"):
        if not isinstance(data.get(field), list):
            data[field] = []

    return data

# ---------------------------------------------------------------------------
# Heuristic partial evaluation (API unavailable)
# ---------------------------------------------------------------------------

def _partial_evaluation(question, answer):
    # type: (str, str) -> Dict
    words       = answer.strip().split()
    word_count  = len(words)
    alpha_ratio = sum(1 for c in answer if c.isalpha()) / max(len(answer), 1)

    if word_count >= 80 and alpha_ratio > 0.7:
        tech, comm, conf = 22, 16, 14
        quality    = "Average"
        strengths  = ["Detailed response provided."]
        weaknesses = ["AI evaluation temporarily unavailable — manual review recommended."]
    elif word_count >= 30:
        tech, comm, conf = 12, 10, 8
        quality    = "Poor"
        strengths  = []
        weaknesses = ["Answer is brief.", "AI evaluation temporarily unavailable."]
    else:
        tech, comm, conf = 4, 4, 2
        quality    = "Poor"
        strengths  = []
        weaknesses = ["Answer is very short.", "AI evaluation temporarily unavailable."]

    return {
        "technical_score":     tech,
        "communication_score": comm,
        "confidence_score":    conf,
        "answer_quality":      quality,
        "strengths":           strengths,
        "weaknesses":          weaknesses,
        "improvement_tips": [
            "Provide a more detailed explanation covering core concepts.",
            "For '{}', explain the what, why, and how.".format(question),
        ],
        "follow_up_questions": [],
        "overall_score":       tech + comm + conf,
        "feedback": (
            "AI evaluation service is temporarily unavailable. "
            "This score is based on answer length and structure. "
            "Add GROQ_API_KEY to your environment for full AI evaluation."
        ),
    }

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_answer(question, answer, role):
    # type: (str, str, str) -> Dict
    """
    Main entry point. Always returns a dict. Never raises.

    Keys: technical_score, communication_score, confidence_score,
          answer_quality, strengths, weaknesses, improvement_tips,
          follow_up_questions, overall_score, feedback
    """
    # Step 1 — quality gate (no API call for gibberish/empty)
    low_quality, reason = _is_low_quality(answer)
    if low_quality:
        logger.info("Low-quality answer (%s) — skipping AI call.", reason)
        return _low_quality_result(reason, question)

    # Step 2 — ensure client exists (re-check in case key was added after boot)
    global _groq_client
    if _groq_client is None:
        _groq_client = _build_groq_client()

    if _groq_client is None:
        logger.warning("Groq client unavailable — using heuristic evaluation.")
        return _partial_evaluation(question, answer)

    # Step 3 — call AI
    data = _call_groq(_groq_client, role, question, answer)

    if data is None:
        logger.error("All Groq retries exhausted — using heuristic evaluation.")
        return _partial_evaluation(question, answer)

    # Step 4 — normalise + compute overall
    data    = _normalise(data)
    overall = (
        data["technical_score"]
        + data["communication_score"]
        + data["confidence_score"]
    )
    data["overall_score"] = overall

    # Build readable feedback string for the result template
    parts = []
    if data["strengths"]:
        parts.append("Strengths: " + "; ".join(data["strengths"][:2]) + ".")
    if data["weaknesses"]:
        parts.append("Areas to improve: " + "; ".join(data["weaknesses"][:2]) + ".")
    if data["improvement_tips"]:
        parts.append("Tip: " + data["improvement_tips"][0])

    data["feedback"] = " ".join(parts) if parts else (
        "Answer quality: {}. Score: {}/100.".format(data["answer_quality"], overall)
    )

    logger.info(
        "Evaluation complete — quality=%s overall=%d/100",
        data["answer_quality"], overall,
    )
    return data
