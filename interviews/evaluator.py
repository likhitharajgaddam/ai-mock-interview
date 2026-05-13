"""
AI Evaluation Engine
====================
Handles answer evaluation with:
- Gibberish / low-quality answer detection
- Structured Groq API calls with retry + exponential backoff
- Robust JSON response parsing
- Detailed logging
- No hardcoded fallback strings — every path returns meaningful output
"""

import os
import re
import time
import json
import math
import logging
from groq import Groq

logger = logging.getLogger("interviews.evaluator")

# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def _build_client() -> Groq | None:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        logger.error(
            "GROQ_API_KEY is not set. "
            "Set it in your environment / Railway variables."
        )
        return None
    return Groq(api_key=key)


# Build once at import time; re-checked inside evaluate() so hot-reloads work.
_groq_client: Groq | None = _build_client()


# ---------------------------------------------------------------------------
# Gibberish / low-quality detection
# ---------------------------------------------------------------------------

_GIBBERISH_PATTERN = re.compile(
    r"^[^a-zA-Z0-9\s]{4,}$"          # pure symbols
    r"|(.)\1{5,}"                      # same char repeated 6+ times
    r"|[a-z]{20,}",                    # 20+ lowercase chars with no spaces
    re.IGNORECASE,
)

def _is_low_quality(answer: str) -> tuple[bool, str]:
    """
    Returns (is_low_quality, reason).
    Catches empty, whitespace-only, too-short, and gibberish answers.
    """
    stripped = answer.strip()

    if not stripped:
        return True, "empty"

    if len(stripped) < 10:
        return True, "too_short"

    # Ratio of alphabetic chars — gibberish keyboard spam is mostly non-alpha
    alpha_chars = sum(c.isalpha() for c in stripped)
    if len(stripped) > 5 and (alpha_chars / len(stripped)) < 0.35:
        return True, "gibberish"

    # Word count — single-word answers are not useful
    words = stripped.split()
    if len(words) < 3:
        return True, "too_short"

    return False, ""


def _low_quality_evaluation(answer: str, reason: str, question: str) -> dict:
    """
    Returns a structured evaluation dict for low-quality answers.
    Scores are legitimately low — not a fallback, but an honest assessment.
    """
    messages = {
        "empty": "No answer was provided.",
        "too_short": "The answer is too brief to evaluate meaningfully.",
        "gibberish": (
            "The answer appears to be random keyboard input and does not "
            "address the question."
        ),
    }
    feedback = messages.get(reason, "The answer could not be evaluated.")

    return {
        "technical_score": 0,
        "communication_score": 0,
        "confidence_score": 0,
        "answer_quality": "No Answer",
        "strengths": [],
        "weaknesses": [feedback],
        "improvement_tips": [
            f"Please provide a genuine answer to: '{question}'",
            "Aim for at least 2–3 sentences covering the core concept.",
        ],
        "follow_up_questions": [],
        "overall_score": 0,
        "feedback": feedback,
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a strict senior technical interviewer at a FAANG-level company.
Evaluate the candidate's answer and return ONLY valid JSON — no markdown, no prose.

JSON schema (all fields required):
{
  "technical_score":      <integer 0-40>,
  "communication_score":  <integer 0-30>,
  "confidence_score":     <integer 0-30>,
  "answer_quality":       <"Excellent"|"Good"|"Average"|"Poor"|"No Answer">,
  "strengths":            [<string>, ...],
  "weaknesses":           [<string>, ...],
  "improvement_tips":     [<string>, ...],
  "follow_up_questions":  [<string>, ...]
}

Scoring rules:
- technical_score:     depth, accuracy, completeness of technical content (0-40)
- communication_score: clarity, structure, conciseness (0-30)
- confidence_score:    specificity, use of examples, assertiveness (0-30)
- Total = technical + communication + confidence  (max 100)

Be strict. A vague or single-sentence answer scores 0-15 total.
A solid, detailed answer scores 70-100 total.
"""


def _build_user_prompt(role: str, question: str, answer: str) -> str:
    return (
        f"Role: {role}\n\n"
        f"Question: {question}\n\n"
        f"Candidate Answer: {answer}\n\n"
        "Return the JSON evaluation now."
    )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """
    Tries multiple strategies to extract a JSON object from the model response.
    Returns None if all strategies fail.
    """
    # Strategy 1: direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strategy 2: find first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strategy 3: strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    logger.warning("JSON extraction failed. Raw response:\n%s", text[:500])
    return None


# ---------------------------------------------------------------------------
# API call with retry + exponential backoff
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY  = 1.5   # seconds


def _call_groq(client: Groq, role: str, question: str, answer: str) -> dict | None:
    """
    Calls the Groq API with retry logic.
    Returns a parsed dict on success, None on total failure.
    """
    user_prompt = _build_user_prompt(role, question, answer)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("Groq API call — attempt %d/%d", attempt, _MAX_RETRIES)

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=800,
            )

            raw_text = response.choices[0].message.content
            logger.debug("Raw AI response:\n%s", raw_text)

            parsed = _extract_json(raw_text)
            if parsed is not None:
                return parsed

            logger.warning("Attempt %d: could not parse JSON from response.", attempt)

        except Exception as exc:
            logger.error("Groq API error on attempt %d: %s", attempt, exc)

        if attempt < _MAX_RETRIES:
            delay = _BASE_DELAY * math.pow(2, attempt - 1)
            logger.info("Retrying in %.1f seconds...", delay)
            time.sleep(delay)

    return None


# ---------------------------------------------------------------------------
# Score normalisation
# ---------------------------------------------------------------------------

def _normalise(data: dict) -> dict:
    """
    Clamps all numeric fields to their valid ranges and ensures
    list fields are actually lists.
    """
    def clamp(val, lo, hi, default):
        try:
            return max(lo, min(hi, int(val)))
        except (TypeError, ValueError):
            return default

    data["technical_score"]     = clamp(data.get("technical_score"),     0, 40, 0)
    data["communication_score"] = clamp(data.get("communication_score"), 0, 30, 0)
    data["confidence_score"]    = clamp(data.get("confidence_score"),    0, 30, 0)

    valid_qualities = {"Excellent", "Good", "Average", "Poor", "No Answer"}
    if data.get("answer_quality") not in valid_qualities:
        data["answer_quality"] = "Average"

    for field in ("strengths", "weaknesses", "improvement_tips", "follow_up_questions"):
        if not isinstance(data.get(field), list):
            data[field] = []

    return data


# ---------------------------------------------------------------------------
# Partial evaluation — when AI fails but answer is not gibberish
# ---------------------------------------------------------------------------

def _partial_evaluation(question: str, answer: str) -> dict:
    """
    Generates a meaningful partial evaluation using heuristics when the
    AI API is completely unavailable. Never returns a generic string.
    """
    words      = answer.strip().split()
    word_count = len(words)
    alpha_ratio = sum(c.isalpha() for c in answer) / max(len(answer), 1)

    # Heuristic scoring
    if word_count >= 80 and alpha_ratio > 0.7:
        tech, comm, conf = 22, 16, 14
        quality = "Average"
        strengths = ["Detailed response provided."]
        weaknesses = ["Could not be AI-evaluated — manual review recommended."]
    elif word_count >= 30:
        tech, comm, conf = 12, 10, 8
        quality = "Poor"
        strengths = []
        weaknesses = [
            "Answer is brief.",
            "Could not be AI-evaluated — manual review recommended.",
        ]
    else:
        tech, comm, conf = 4, 4, 2
        quality = "Poor"
        strengths = []
        weaknesses = [
            "Answer is very short.",
            "Could not be AI-evaluated — manual review recommended.",
        ]

    return {
        "technical_score":     tech,
        "communication_score": comm,
        "confidence_score":    conf,
        "answer_quality":      quality,
        "strengths":           strengths,
        "weaknesses":          weaknesses,
        "improvement_tips": [
            "Provide a more detailed explanation covering core concepts.",
            f"For '{question}', aim to explain the what, why, and how.",
        ],
        "follow_up_questions": [],
        "overall_score":       tech + comm + conf,
        "feedback": (
            "AI evaluation service is temporarily unavailable. "
            "This is a heuristic score based on answer length and quality. "
            "Please retry for a full AI evaluation."
        ),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_answer(question: str, answer: str, role: str) -> dict:
    """
    Main entry point.

    Returns a dict with keys:
        technical_score, communication_score, confidence_score,
        answer_quality, strengths, weaknesses, improvement_tips,
        follow_up_questions, overall_score, feedback

    Never raises. Never returns a generic "Fallback evaluation." string.
    """
    # --- Step 1: quality gate ---
    low_quality, reason = _is_low_quality(answer)
    if low_quality:
        logger.info("Low-quality answer detected (%s). Skipping AI call.", reason)
        result = _low_quality_evaluation(answer, reason, question)
        result["overall_score"] = 0
        result["feedback"] = result["weaknesses"][0] if result["weaknesses"] else "No answer provided."
        return result

    # --- Step 2: ensure client is available ---
    global _groq_client
    if _groq_client is None:
        _groq_client = _build_client()   # retry in case key was added after startup

    if _groq_client is None:
        logger.error("Groq client unavailable — returning partial evaluation.")
        return _partial_evaluation(question, answer)

    # --- Step 3: call AI ---
    data = _call_groq(_groq_client, role, question, answer)

    if data is None:
        logger.error("All Groq retries exhausted — returning partial evaluation.")
        return _partial_evaluation(question, answer)

    # --- Step 4: normalise ---
    data = _normalise(data)
    overall = (
        data["technical_score"]
        + data["communication_score"]
        + data["confidence_score"]
    )
    data["overall_score"] = overall

    # Build a human-readable feedback string for the existing result template
    parts = []
    if data["strengths"]:
        parts.append("Strengths: " + "; ".join(data["strengths"][:2]) + ".")
    if data["weaknesses"]:
        parts.append("Areas to improve: " + "; ".join(data["weaknesses"][:2]) + ".")
    if data["improvement_tips"]:
        parts.append("Tip: " + data["improvement_tips"][0])

    data["feedback"] = " ".join(parts) if parts else (
        f"Answer quality: {data['answer_quality']}. Score: {overall}/100."
    )

    logger.info(
        "Evaluation complete — quality=%s overall=%d/100",
        data["answer_quality"],
        overall,
    )
    return data
