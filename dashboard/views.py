from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Avg
from interviews.models import InterviewSession
from interviews.views import ROLE_DOMAIN, DOMAIN_META, DOMAIN_LEVEL_THRESHOLDS
import json


def _xp_from_score(score):
    # type: (int) -> int
    """Same formula as views.py — derive XP from a 0-10 answer score."""
    if score <= 2:   return 0
    elif score <= 4: return 5
    elif score <= 6: return 15
    elif score <= 8: return 30
    else:            return 50


def _domain_level(xp):
    # type: (int) -> int
    level = 1
    for threshold in DOMAIN_LEVEL_THRESHOLDS[1:]:
        if xp >= threshold:
            level += 1
        else:
            break
    return min(level, len(DOMAIN_LEVEL_THRESHOLDS))


@login_required
def dashboard_view(request):
    sessions = InterviewSession.objects.filter(
        user=request.user
    ).order_by("created_at")

    total_interviews = sessions.count()

    average_score = sessions.aggregate(avg_score=Avg("total_score"))["avg_score"] or 0
    average_score = round(average_score, 2)

    highest_session = sessions.order_by("-total_score").first()
    highest_score   = highest_session.total_score if highest_session else 0

    lowest_session  = sessions.order_by("total_score").first()
    lowest_score    = lowest_session.total_score if lowest_session else 0

    if average_score >= 80:   performance_level = "Advanced"
    elif average_score >= 50: performance_level = "Intermediate"
    else:                     performance_level = "Beginner"

    labels = [s.created_at.strftime("%d %b") for s in sessions]
    scores = [s.total_score for s in sessions]

    # ── Domain XP breakdown from actual answer scores ───────────────
    domain_xp = {}   # domain_key -> total XP
    for session in sessions:
        domain = ROLE_DOMAIN.get(session.job_role.name, "backend")
        for ans in session.answer_set.all():
            domain_xp[domain] = domain_xp.get(domain, 0) + _xp_from_score(ans.score)

    # Build domain cards for template
    domain_cards = []
    for domain_key, xp in sorted(domain_xp.items(), key=lambda x: -x[1]):
        meta  = DOMAIN_META.get(domain_key, {})
        level = _domain_level(xp)
        next_threshold = DOMAIN_LEVEL_THRESHOLDS[level] if level < len(DOMAIN_LEVEL_THRESHOLDS) else None
        career_titles  = meta.get("career", [])
        current_title  = career_titles[min(level - 1, len(career_titles) - 1)] if career_titles else domain_key
        next_title     = career_titles[min(level, len(career_titles) - 1)] if level < len(career_titles) else "Max Level"
        progress_pct   = 0
        if next_threshold:
            prev_threshold = DOMAIN_LEVEL_THRESHOLDS[level - 1]
            span = next_threshold - prev_threshold
            earned_in_level = xp - prev_threshold
            progress_pct = min(100, int((earned_in_level / span) * 100)) if span > 0 else 100

        domain_cards.append({
            "key":           domain_key,
            "label":         meta.get("label", domain_key),
            "icon":          meta.get("icon", "💻"),
            "color":         meta.get("color", "#a78bfa"),
            "xp":            xp,
            "level":         level,
            "current_title": current_title,
            "next_title":    next_title,
            "progress_pct":  progress_pct,
            "next_steps":    meta.get("next", []),
        })

    # Primary domain = highest XP domain
    primary_domain = domain_cards[0] if domain_cards else None

    # Career recommendations based on primary domain
    recommendations = []
    if primary_domain:
        meta = DOMAIN_META.get(primary_domain["key"], {})
        recommendations = meta.get("next", [])

    context = {
        "sessions":          sessions.order_by("-created_at"),
        "total_interviews":  total_interviews,
        "average_score":     average_score,
        "highest_score":     highest_score,
        "lowest_score":      lowest_score,
        "performance_level": performance_level,
        "labels":            json.dumps(labels),
        "scores":            json.dumps(scores),
        "domain_cards":      domain_cards,
        "primary_domain":    primary_domain,
        "recommendations":   recommendations,
    }

    return render(request, "dashboard.html", context)


@login_required
def session_detail(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id, user=request.user)
    answers = session.answer_set.all()
    return render(request, "session_detail.html", {
        "session": session,
        "answers": answers,
    })
