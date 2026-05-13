"""
Global context processor — injects user_total_xp into every template.

This is the single source of truth for XP. It replaces the fragile
localStorage sync that only ran on the dashboard page.
"""


def user_xp(request):
    """
    Returns {'user_total_xp': <int>} for every authenticated request.
    Unauthenticated requests get 0.

    XP formula (same as dashboard/views.py):
        score 0-2  -> 0 XP
        score 3-4  -> 5 XP
        score 5-6  -> 15 XP
        score 7-8  -> 30 XP
        score 9-10 -> 50 XP
    """
    if not request.user.is_authenticated:
        return {"user_total_xp": 0}

    try:
        from interviews.models import Answer, InterviewSession

        def _xp(score):
            if score <= 2:   return 0
            elif score <= 4: return 5
            elif score <= 6: return 15
            elif score <= 8: return 30
            else:            return 50

        sessions = InterviewSession.objects.filter(
            user=request.user
        ).prefetch_related("answer_set")

        total = 0
        for session in sessions:
            for ans in session.answer_set.all():
                total += _xp(ans.score)

        return {"user_total_xp": total}

    except Exception:
        # Never crash a page render because of XP calculation
        return {"user_total_xp": 0}
