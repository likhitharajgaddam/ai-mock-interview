"""
AI Evaluation Engine
====================
Uses direct HTTPS requests to Groq API — no SDK dependency.
This bypasses all httpx/proxies compatibility issues entirely.

Pipeline:
  1. Quality gate  — skip API for empty/gibberish answers
  2. Direct HTTP   — POST to api.groq.com/openai/v1/chat/completions
  3. JSON extract  — 3 strategies (direct, regex, strip fences)
  4. Normalise     — clamp scores, validate fields
  5. Heuristic     — meaningful fallback if API completely unavailable
"""

import json
import logging
import math
import os
import re
import time
import urllib.request
import urllib.error
from typing import Dict, Optional, Tuple

logger = logging.getLogger("interviews.evaluator")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------

def _get_api_key():
    # type: () -> Optional[str]
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        logger.warning(
            "[GROQ] GROQ_API_KEY is NOT set. "
            "Add it in Render > Environment > GROQ_API_KEY"
        )
        return None
    if not key.startswith("gsk_"):
        logger.warning(
            "[GROQ] Key format looks wrong (expected gsk_...). "
            "First 6 chars: %s", key[:6]
        )
    logger.info("[GROQ] API key loaded. Preview: %s...%s", key[:8], key[-4:])
    return key

# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _is_low_quality(answer):
    # type: (str) -> Tuple[bool, str]
    s = answer.strip()
    if not s:
        return True, "empty"
    if len(s) < 10:
        return True, "too_short"
    alpha = sum(1 for c in s if c.isalpha())
    if len(s) > 5 and (alpha / len(s)) < 0.35:
        return True, "gibberish"
    if len(s.split()) < 3:
        return True, "too_short"
    return False, ""


def _low_quality_result(reason, question):
    # type: (str, str) -> Dict
    msgs = {
        "empty":     "No answer was provided.",
        "too_short": "The answer is too brief to evaluate meaningfully.",
        "gibberish": "The answer appears to be random input and does not address the question.",
    }
    fb = msgs.get(reason, "The answer could not be evaluated.")
    return {
        "technical_score": 0, "communication_score": 0, "confidence_score": 0,
        "answer_quality": "No Answer", "strengths": [], "weaknesses": [fb],
        "improvement_tips": [
            "Please provide a genuine answer to: '{}'".format(question),
            "Aim for at least 2-3 sentences covering the core concept.",
        ],
        "follow_up_questions": [], "overall_score": 0, "feedback": fb,
    }

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a strict senior technical interviewer at a FAANG-level company. "
    "Evaluate the candidate answer and return ONLY a valid JSON object. "
    "No markdown, no code fences, no text outside the JSON.\n\n"
    "Required JSON schema:\n"
    "{\n"
    '  "technical_score": <integer 0-40>,\n'
    '  "communication_score": <integer 0-30>,\n'
    '  "confidence_score": <integer 0-30>,\n'
    '  "answer_quality": <"Excellent"|"Good"|"Average"|"Poor"|"No Answer">,\n'
    '  "strengths": [<string>, ...],\n'
    '  "weaknesses": [<string>, ...],\n'
    '  "improvement_tips": [<string>, ...],\n'
    '  "follow_up_questions": [<string>, ...]\n'
    "}\n\n"
    "Scoring: technical(0-40) + communication(0-30) + confidence(0-30) = total(0-100)\n"
    "Vague 1-sentence answer: 0-15. Partial answer: 20-50. "
    "Solid detailed answer: 60-85. Exceptional: 86-100."
)


def _user_msg(role, question, answer):
    # type: (str, str, str) -> str
    return (
        "Role: {}\n\n"
        "Interview Question: {}\n\n"
        "Candidate Answer: {}\n\n"
        "Return the JSON evaluation now."
    ).format(role, question, answer)

# ---------------------------------------------------------------------------
# JSON extraction — 3 strategies
# ---------------------------------------------------------------------------

def _extract_json(text):
    # type: (str) -> Optional[Dict]
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    logger.warning("[GROQ] JSON extraction failed. Raw: %.300s", text)
    return None

# ---------------------------------------------------------------------------
# Direct HTTP call — no SDK, no proxy issues
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY  = 1.0


def _call_groq_http(api_key, role, question, answer):
    # type: (str, str, str, str) -> Optional[Dict]
    """
    Calls Groq API directly via urllib — zero external dependencies beyond
    the standard library. Completely bypasses httpx/proxies issues.
    """
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": _user_msg(role, question, answer)},
        ],
        "temperature": 0.3,
        "max_tokens":  900,
    }).encode("utf-8")

    headers = {
        "Authorization": "Bearer {}".format(api_key),
        "Content-Type":  "application/json",
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("[GROQ] HTTP attempt %d/%d", attempt, _MAX_RETRIES)

            req  = urllib.request.Request(
                GROQ_API_URL, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")

            data = json.loads(body)
            raw  = data["choices"][0]["message"]["content"]
            logger.debug("[GROQ] Raw response: %.400s", raw)

            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info("[GROQ] Attempt %d succeeded.", attempt)
                return parsed

            logger.warning("[GROQ] Attempt %d: JSON parse failed.", attempt)

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error("[GROQ] HTTP %d on attempt %d: %s", exc.code, attempt, body[:300])
        except urllib.error.URLError as exc:
            logger.error("[GROQ] URL error on attempt %d: %s", attempt, exc.reason)
        except Exception as exc:
            logger.error("[GROQ] Unexpected error on attempt %d: %s: %s",
                         attempt, type(exc).__name__, exc)

        if attempt < _MAX_RETRIES:
            delay = _BASE_DELAY * math.pow(2, attempt - 1)
            logger.info("[GROQ] Retrying in %.1fs...", delay)
            time.sleep(delay)

    logger.error("[GROQ] All %d attempts failed.", _MAX_RETRIES)
    return None

# ---------------------------------------------------------------------------
# Normalise
# ---------------------------------------------------------------------------

def _normalise(data):
    # type: (Dict) -> Dict
    def clamp(v, lo, hi, d):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return d

    data["technical_score"]     = clamp(data.get("technical_score"),     0, 40, 0)
    data["communication_score"] = clamp(data.get("communication_score"), 0, 30, 0)
    data["confidence_score"]    = clamp(data.get("confidence_score"),    0, 30, 0)

    valid = {"Excellent", "Good", "Average", "Poor", "No Answer"}
    if data.get("answer_quality") not in valid:
        data["answer_quality"] = "Average"

    for f in ("strengths", "weaknesses", "improvement_tips", "follow_up_questions"):
        if not isinstance(data.get(f), list):
            data[f] = []
        data[f] = [str(x) for x in data[f] if x]

    return data

# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------

def _heuristic(question, answer):
    # type: (str, str) -> Dict
    wc = len(answer.strip().split())
    ar = sum(1 for c in answer if c.isalpha()) / max(len(answer), 1)

    if wc >= 80 and ar > 0.7:
        t, c, f = 22, 16, 14
        q = "Average"
        s = ["Detailed response provided."]
        w = ["AI evaluation temporarily unavailable."]
    elif wc >= 30:
        t, c, f = 12, 10, 8
        q = "Poor"
        s = []
        w = ["Answer is brief.", "AI evaluation temporarily unavailable."]
    else:
        t, c, f = 4, 4, 2
        q = "Poor"
        s = []
        w = ["Answer is very short.", "AI evaluation temporarily unavailable."]

    return {
        "technical_score": t, "communication_score": c, "confidence_score": f,
        "answer_quality": q, "strengths": s, "weaknesses": w,
        "improvement_tips": [
            "Explain the what, why, and how with concrete examples.",
            "For '{}', cover the core concept in 3-4 sentences.".format(question[:80]),
        ],
        "follow_up_questions": [],
        "overall_score": t + c + f,
        "feedback": (
            "Heuristic score (AI temporarily unavailable). "
            "Check /interview/api/status/ to diagnose."
        ),
    }

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_answer(question, answer, role):
    # type: (str, str, str) -> Dict
    """Always returns a dict. Never raises."""

    # Step 1 — quality gate
    low_q, reason = _is_low_quality(answer)
    if low_q:
        logger.info("[EVAL] Low-quality (%s) — skipping API.", reason)
        return _low_quality_result(reason, question)

    # Step 2 — get key
    api_key = _get_api_key()
    if not api_key:
        return _heuristic(question, answer)

    # Step 3 — call API
    data = _call_groq_http(api_key, role, question, answer)
    if data is None:
        return _heuristic(question, answer)

    # Step 4 — normalise
    data    = _normalise(data)
    overall = (data["technical_score"]
               + data["communication_score"]
               + data["confidence_score"])
    data["overall_score"] = overall

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
