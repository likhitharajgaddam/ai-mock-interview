import json
import os
import re
import random
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from groq import Groq

from .evaluator import evaluate_answer
from .models import Answer, InterviewSession, JobRole

logger = logging.getLogger("interviews.views")

MAX_QUESTIONS = 8

# ---------------------------------------------------------------------------
# Fallback question bank (used only when AI question generation fails)
# ---------------------------------------------------------------------------

FALLBACK_QUESTIONS = {
    "Software Developer": [
        "Explain REST architecture.",
        "What is dependency injection?",
        "Explain microservices architecture.",
        "What is database indexing?",
        "Difference between SQL and NoSQL?",
        "Explain caching strategies.",
        "What is JWT authentication?",
        "Explain SOLID principles.",
    ],
    "Cyber Security Analyst": [
        "What is a SIEM?",
        "Explain XSS and CSRF.",
        "What is OWASP Top 10?",
        "Explain brute force attack prevention.",
        "What is privilege escalation?",
        "Difference between IDS and IPS?",
        "Explain Zero Trust security.",
        "What is a SOC workflow?",
    ],
    "Data Analyst": [
        "Explain data normalisation.",
        "What is EDA?",
        "Difference between supervised and unsupervised learning?",
        "Explain data cleaning techniques.",
        "What is regression analysis?",
        "Explain SQL joins.",
        "What is data visualisation best practice?",
        "Explain correlation vs causation.",
    ],
    "AI / ML Engineer": [
        "Explain overfitting and underfitting.",
        "What is gradient descent?",
        "Difference between CNN and RNN?",
        "Explain model evaluation metrics.",
        "What is feature engineering?",
        "Explain bias vs variance.",
        "What is transfer learning?",
        "Explain hyperparameter tuning.",
    ],
    "DevOps Engineer": [
        "Explain CI/CD pipeline design.",
        "What is Infrastructure as Code?",
        "How does Docker differ from virtual machines?",
        "Explain Kubernetes architecture.",
        "What is blue-green deployment?",
        "How do you monitor distributed systems?",
        "Explain container orchestration.",
        "How would you secure a CI/CD pipeline?",
    ],
    "Cloud Engineer": [
        "Explain IAM in cloud platforms.",
        "What is auto scaling?",
        "How does load balancing work?",
        "Explain VPC architecture.",
        "How do you secure cloud storage?",
        "Difference between IaaS, PaaS, and SaaS?",
        "Explain cloud cost optimisation strategies.",
        "How do you design high availability systems?",
    ],
    "Frontend Developer": [
        "What is virtual DOM?",
        "Explain state management in React.",
        "How does browser rendering work?",
        "What is lazy loading?",
        "Explain responsive design principles.",
        "How do you optimise frontend performance?",
        "What are web accessibility best practices?",
        "Explain CORS.",
    ],
    "Backend Engineer": [
        "Explain RESTful API design principles.",
        "How do you implement authentication in Django?",
        "What is database indexing?",
        "Explain caching in backend systems.",
        "How would you design a scalable backend?",
        "What are message queues?",
        "Explain rate limiting.",
        "How do you handle concurrency?",
    ],
    "Site Reliability Engineer": [
        "What is observability?",
        "Explain incident response workflow.",
        "How do you handle system outages?",
        "What is SLA, SLO, and SLI?",
        "Explain load testing.",
        "How do you monitor microservices?",
        "What is root cause analysis?",
        "Explain reliability engineering principles.",
    ],
    "Blockchain Developer": [
        "What is a smart contract?",
        "Explain consensus mechanisms.",
        "What is gas in Ethereum?",
        "How do you secure a smart contract?",
        "Difference between public and private blockchain?",
        "Explain token standards like ERC-20.",
        "What is Web3?",
        "How do you prevent reentrancy attacks?",
    ],
    "Product Data Scientist": [
        "Explain A/B testing.",
        "How do you measure product success?",
        "What is cohort analysis?",
        "Explain hypothesis testing.",
        "How do you design experiments?",
        "What are business KPIs?",
        "Explain churn prediction.",
        "How do you communicate data insights?",
    ],
    "Full Stack Web Developer": [
        "Explain how frontend and backend communicate.",
        "What is JWT authentication?",
        "How would you design a scalable web app?",
        "Explain database normalisation.",
        "How do you deploy a web application?",
        "What is CORS?",
        "Explain MVC architecture.",
        "How do you secure a web application?",
    ],
}


# ---------------------------------------------------------------------------
# Groq client for question generation (separate from evaluator)
# ---------------------------------------------------------------------------

def _get_groq_client() -> Groq | None:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        logger.warning("GROQ_API_KEY not set — AI question generation disabled.")
        return None
    return Groq(api_key=key)


# ---------------------------------------------------------------------------
# AI question generation
# ---------------------------------------------------------------------------

def generate_ai_questions_logic(role, count: int = 8) -> list[str]:
    client = _get_groq_client()
    if client is None:
        return _fallback_questions(role)

    prompt = (
        f"Generate {count} different advanced technical interview questions.\n\n"
        f"Role: {role.name}\n"
        f"Description: {role.description}\n\n"
        "Return only numbered questions, one per line."
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=600,
        )
        text = response.choices[0].message.content.strip()
        questions = []
        for line in text.split("\n"):
            line = line.strip()
            if line:
                # Strip leading "1. " / "1) " numbering
                line = re.sub(r"^\d+[\.\)]\s*", "", line)
                if line:
                    questions.append(line)
        if questions:
            return questions[:count]
    except Exception as exc:
        logger.error("AI question generation failed: %s", exc)

    return _fallback_questions(role)


def _fallback_questions(role) -> list[str]:
    questions = FALLBACK_QUESTIONS.get(
        role.name,
        random.choice(list(FALLBACK_QUESTIONS.values())),
    )
    return list(questions)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def home(request):
    if request.user.is_authenticated:
        return redirect("select_role")
    return render(request, "home.html")


def about(request):
    return render(request, "about.html")


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("login")
    else:
        form = UserCreationForm()
    return render(request, "register.html", {"form": form})


@never_cache
@login_required
def select_role(request):
    # Clear all in-progress interview sessions when returning to role selection
    keys_to_remove = [k for k in request.session.keys() if k.startswith("interview_role_")]
    for key in keys_to_remove:
        request.session.pop(key, None)

    roles = JobRole.objects.all()
    return render(request, "select_role.html", {"roles": roles})


@never_cache
@login_required
def start_interview(request, role_id):
    role = JobRole.objects.get(id=role_id)
    session_key = f"interview_role_{role_id}"

    # Explicit restart
    if request.GET.get("restart") == "true":
        request.session.pop(session_key, None)
        return redirect("start_interview", role_id=role.id)

    # Initialise session if not present
    if session_key not in request.session:
        questions = generate_ai_questions_logic(role, MAX_QUESTIONS)
        random.shuffle(questions)
        request.session[session_key] = {
            "question_number": 1,
            "questions": questions,
            "total_score": 0,
            "answers": [],
        }

    interview_data = request.session[session_key]
    question_number = interview_data["question_number"]
    questions = interview_data["questions"]

    # ---- Interview complete ----
    if question_number > MAX_QUESTIONS:
        total_raw = interview_data["total_score"]
        # total_raw is sum of overall_score (0-100 each); normalise to percentage
        percentage = int((total_raw / (MAX_QUESTIONS * 100)) * 100)
        percentage = max(0, min(100, percentage))

        interview_session = InterviewSession.objects.create(
            user=request.user,
            job_role=role,
            total_score=percentage,
        )

        for ans in interview_data["answers"]:
            Answer.objects.create(
                session=interview_session,
                question_text=ans["question"],
                response=ans["user_answer"],
                score=ans["score"],
                feedback=ans["feedback"],
            )

        request.session.pop(session_key, None)
        return redirect("interview_result", session_id=interview_session.id)

    question = questions[question_number - 1]

    # ---- Handle POST (answer submission) ----
    if request.method == "POST":
        user_answer = request.POST.get("answer", "").strip()

        if not user_answer:
            return render(request, "interview.html", {
                "role": role,
                "question": question,
                "question_number": question_number,
                "progress_percentage": int(((question_number - 1) / MAX_QUESTIONS) * 100),
                "error": "Please write an answer before submitting.",
            })

        # ---- Core evaluation call ----
        evaluation = evaluate_answer(
            question=question,
            answer=user_answer,
            role=role.name,
        )

        # Map 0-100 overall_score to a 0-10 display score for the result page
        overall = evaluation.get("overall_score", 0)
        display_score = round(overall / 10)

        interview_data["answers"].append({
            "question":    question,
            "user_answer": user_answer,
            "score":       display_score,
            "feedback":    evaluation.get("feedback", ""),
            # Store full evaluation for future analytics
            "evaluation":  {
                "technical_score":     evaluation.get("technical_score", 0),
                "communication_score": evaluation.get("communication_score", 0),
                "confidence_score":    evaluation.get("confidence_score", 0),
                "answer_quality":      evaluation.get("answer_quality", ""),
                "strengths":           evaluation.get("strengths", []),
                "weaknesses":          evaluation.get("weaknesses", []),
                "improvement_tips":    evaluation.get("improvement_tips", []),
                "follow_up_questions": evaluation.get("follow_up_questions", []),
            },
        })

        interview_data["total_score"] += overall
        interview_data["question_number"] += 1
        request.session[session_key] = interview_data

        return redirect(request.path)

    # ---- GET — render question ----
    progress_percentage = int(((question_number - 1) / MAX_QUESTIONS) * 100)
    return render(request, "interview.html", {
        "role": role,
        "question": question,
        "question_number": question_number,
        "progress_percentage": progress_percentage,
    })


@login_required
def interview_result(request, session_id):
    session = InterviewSession.objects.get(id=session_id, user=request.user)
    answers = session.answer_set.all()
    return render(request, "result.html", {
        "role": session.job_role,
        "percentage": session.total_score,
        "answers": answers,
    })


def generate_ai_question(request):
    """API endpoint — returns AI-generated questions for a role."""
    role_name = request.GET.get("role", "Software Developer")
    try:
        role = JobRole.objects.get(name=role_name)
    except JobRole.DoesNotExist:
        return JsonResponse({"questions": FALLBACK_QUESTIONS["Software Developer"]})

    questions = generate_ai_questions_logic(role)
    return JsonResponse({"questions": questions})
