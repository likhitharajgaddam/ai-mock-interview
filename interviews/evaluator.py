"""
AI Evaluation Engine
====================
Production-safe. Never raises. Never returns a generic string.

Pipeline:
  1. Quality gate  — detect empty / gibberish before wasting an API call
  2. Groq API call — structured JSON prompt, 3 retries + exponential backoff
  3. JSON extract  — 3 strategies (direct, regex, strip fences)
  4. Normalise     — clamp scores, validate enums, ensure list fields
  5. Heuristic     — meaningful fallback when API is completely unavailable
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
# Groq client — lazy import, never crashes startup
# ---------------------------------------------------------------------------

def _build_groq_client():
    # type: () -> Optional[object]
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        logger.warning(
            "[GROQ] GROQ_API_KEY environment variable is NOT set. "
            "Go to Render > Environment and add: GROQ_API_KEY = gsk_..."
        )
        return None
    if not key.startswith("gsk_"):
        logger.warning(
            "[GROQ] GROQ_API_KEY looks invalid (should start with 'gsk_'). "
            "Current value starts with: %s", key[:6]
        )
    try:
        from groq import Groq  # type: ignore
        client = Groq(api_key=key)
        logger.info("[GROQ] Client initialised successfully.")
        return client
    except ImportError:
        logger.error("[GROQ] groq package not installed. Check requirements.txt.")
        return None
    except Exception as exc:
        logger.error("[GROQ] Client init failed: %s", exc)
        return None


_groq_client = _build_groq_client()

# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _is_low_quality(answer):
    # type: (str) -> Tuple[bool, str]
    stripped = answer.strip()
    if not stripped:
        return True, "empty"
    if len(stripped) < 10:
        return True, "too_short"
    alpha = sum(1 for c in stripped if c.isalpha())
    if len(stripped) > 5 and (alpha / len(stripped)) < 0.35:
        return True, "gibberish"
    if len(stripped.split()) < 3:
        return True, "too_short"
    return False, ""


def _low_quality_result(reason, question):
    # type: (str, str) -> Dict
    msgs = {
        "empty":     "No answer was provided.",
        "too_short": "The answer is too brief to evaluate meaningfully.",
        "gibberish": "The answer appears to be random input and does not address the question.",
    }
    feedback = msgs.get(reason, "The answer could not be evaluated.")
    return {
        "technical_score":     0,
        "communication_score": 0,
        "confidence_score":    0,
        "answer_quality":      "No Answer",
        "strengths":           [],
        "weaknesses":          [feedback],
        "improvement_tips":    [
            "Please provide a genuine answer to: '{}'".format(question),
            "Aim for at least 2-3 sentences covering the core concept.",
        ],
        "follow_up_questions": [],
        "overall_score":       0,
        "feedback":            feedback,
    }

# ---------------------------------------------------------------------------
# Prompt — instructs model to return ONLY JSON
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = "\n".join([
    "You are a strict senior technical interviewer at a FAANG-level company.",
    "Evaluate the candidate answer and return ONLY a valid JSON object.",
    "Do NOT include markdown, code fences, or any text outside the JSON.",
    "",
    "Required JSON schema:",
    "{",
    '  "technical_score": <integer 0-40>,',
    '  "communication_score": <integer 0-30>,',
    '  "confidence_score": <integer 0-30>,',
    '  "answer_quality": <"Excellent"|"Good"|"Average"|"Poor"|"No Answer">,',
    '  "strengths": [<string>, ...],',
    '  "weaknesses": [<string>, ...],',
    '  "improvement_tips": [<string>, ...],',
    '  "follow_up_questions": [<string>, ...]',
    "}",
    "",
    "Scoring guide:",
    "  technical_score:     accuracy, depth, completeness of technical content (0-40)",
    "  communication_score: clarity, structure, conciseness (0-30)",
    "  confidence_score:    use of examples, specificity, assertiveness (0-30)",
    "  Total max = 100",
    "",
    "Be strict and realistic:",
    "  - Vague or 1-sentence answer  -> 0-15 total",
    "  - Partial but relevant answer -> 20-50 total",
    "  - Solid detailed answer       -> 60-85 total",
    "  - Exceptional answer          -> 86-100 total",
])


def _user_prompt(role, question, answer):
    # type: (str, str, str) -> str
    return (
        "Role: {role}\n\n"
        "Interview Question: {question}\n\n"
        "Candidate Answer: {answer}\n\n"
        "Return the JSON evaluation object now."
    ).format(role=role, question=question, answer=answer)

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

    # Strategy 2: find outermost { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: strip markdown fences then parse
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning("[GROQ] JSON extraction failed. Raw: %s", text[:400])
    return None

# ---------------------------------------------------------------------------
# API call with retry + exponential backoff
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY  = 1.0  # seconds


def _call_groq(client, role, question, answer):
    # type: (object, str, str, str) -> Optional[Dict]
    prompt = _user_prompt(role, question, answer)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("[GROQ] Attempt %d/%d for question: %.60s",
                        attempt, _MAX_RETRIES, question)

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.3,
                max_tokens=900,
            )

            raw = response.choices[0].message.content
            logger.debug("[GROQ] Raw response: %s", raw[:500])

            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info("[GROQ] Attempt %d succeeded.", attempt)
                return parsed

            logger.warning("[GROQ] Attempt %d: JSON parse failed.", attempt)

        except Exception as exc:
            logger.error("[GROQ] Attempt %d error: %s: %s",
                         attempt, type(exc).__name__, exc)

        if attempt < _MAX_RETRIES:
            delay = _BASE_DELAY * math.pow(2, attempt - 1)
            logger.info("[GROQ] Retrying in %.1fs...", delay)
            time.sleep(delay)

    logger.error("[GROQ] All %d attempts failed.", _MAX_RETRIES)
    return None

# ---------------------------------------------------------------------------
# Normalise scores
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
        # Ensure each item is a plain string
        data[field] = [str(x) for x in data[field] if x]

    return data

# ---------------------------------------------------------------------------
# Heuristic fallback — meaningful, never generic
# ---------------------------------------------------------------------------

def _heuristic(question, answer):
    # type: (str, str) -> Dict
    words      = answer.strip().split()
    wc         = len(words)
    alpha_r    = sum(1 for c in answer if c.isalpha()) / max(len(answer), 1)

    if wc >= 80 and alpha_r > 0.7:
        tech, comm, conf = 22, 16, 14
        quality   = "Average"
        strengths = ["Detailed response with good length."]
        weak      = ["Could not be AI-evaluated — please ensure GROQ_API_KEY is set on Render."]
    elif wc >= 30:
        tech, comm, conf = 12, 10, 8
        quality   = "Poor"
        strengths = []
        weak      = ["Answer is brief.", "AI evaluation unavailable — check GROQ_API_KEY on Render."]
    else:
        tech, comm, conf = 4, 4, 2
        quality   = "Poor"
        strengths = []
        weak      = ["Answer is very short.", "AI evaluation unavailable — check GROQ_API_KEY on Render."]

    return {
        "technical_score":     tech,
        "communication_score": comm,
        "confidence_score":    conf,
        "answer_quality":      quality,
        "strengths":           strengths,
        "weaknesses":          weak,
        "improvement_tips": [
            "Provide a detailed explanation covering the what, why, and how.",
            "For '{}', structure your answer with examples.".format(question[:80]),
        ],
        "follow_up_questions": [],
        "overall_score":       tech + comm + conf,
        "feedback": (
            "Scored using length-based heuristics (AI unavailable). "
            "To enable full AI evaluation, add GROQ_API_KEY to Render environment variables."
        ),
    }

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_answer(question, answer, role):
    # type: (str, str, str) -> Dict
    """
    Always returns a dict. Never raises.
    Keys: technical_score, communication_score, confidence_score,
          answer_quality, strengths, weaknesses, improvement_tips,
          follow_up_questions, overall_score, feedback
    """
    # Step 1 — quality gate
    low_q, reason = _is_low_quality(answer)
    if low_q:
        logger.info("[EVAL] Low-quality answer (%s) — skipping API.", reason)
        return _low_quality_result(reason, question)

    # Step 2 — ensure client (re-check if key was added after boot)
    global _groq_client
    if _groq_client is None:
        _groq_client = _build_groq_client()

    if _groq_client is None:
        logger.warning("[EVAL] No Groq client — using heuristic.")
        return _heuristic(question, answer)

    # Step 3 — call AI
    data = _call_groq(_groq_client, role, question, answer)
    if data is None:
        logger.error("[EVAL] Groq failed — using heuristic.")
        return _heuristic(question, answer)

    # Step 4 — normalise
    data    = _normalise(data)
    overall = (data["technical_score"]
               + data["communication_score"]
               + data["confidence_score"])
    data["overall_score"] = overall

    # Build readable feedback string
    parts = []
    if data["strengths"]:
        parts.append("Strengths: " + "; ".join(data["strengths"][:2]) + ".")
    if data["weaknesses"]:
        parts.append("Improve: " + "; ".join(data["weaknesses"][:2]) + ".")
    if data["improvement_tips"]:
        parts.append("Tip: " + data["improvement_tips"][0])
    data["feedback"] = " ".join(parts) if parts else (
        "Quality: {}. Score: {}/100.".format(data["answer_quality"], overall)
    )

    logger.info("[EVAL] Done — quality=%s score=%d/100",
                data["answer_quality"], overall)
    return data
