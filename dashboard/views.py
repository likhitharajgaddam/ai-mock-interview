from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Avg
from interviews.models import InterviewSession
import json


@login_required
def dashboard_view(request):
    sessions = InterviewSession.objects.filter(
        user=request.user
    ).order_by("created_at")

    total_interviews = sessions.count()

    # Average
    average_score = sessions.aggregate(
        avg_score=Avg("total_score")
    )["avg_score"] or 0
    average_score = round(average_score, 2)

    # Highest
    highest_session = sessions.order_by("-total_score").first()
    highest_score = highest_session.total_score if highest_session else 0

    # Lowest
    lowest_session = sessions.order_by("total_score").first()
    lowest_score = lowest_session.total_score if lowest_session else 0

    # Performance Level
    if average_score >= 80:
        performance_level = "Advanced"
    elif average_score >= 50:
        performance_level = "Intermediate"
    else:
        performance_level = "Beginner"

    # Graph
    labels = [s.created_at.strftime("%d %b") for s in sessions]
    scores = [s.total_score for s in sessions]

    context = {
        "sessions": sessions.order_by("-created_at"),
        "total_interviews": total_interviews,
        "average_score": average_score,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "performance_level": performance_level,
        "labels": json.dumps(labels),
        "scores": json.dumps(scores),
    }

    return render(request, "dashboard.html", context)

@login_required
def session_detail(request, session_id):
    session = get_object_or_404(
        InterviewSession,
        id=session_id,
        user=request.user
    )

    answers = session.answer_set.all()

    return render(request, "session_detail.html", {
        "session": session,
        "answers": answers
    })