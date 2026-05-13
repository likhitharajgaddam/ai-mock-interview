import os
import re
import random
import logging
from typing import List, Optional

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from .evaluator import evaluate_answer
from .models import Answer, InterviewSession, JobRole

logger = logging.getLogger("interviews.views")

MAX_QUESTIONS = 8

# ---------------------------------------------------------------------------
# Fallback question bank — used when AI generation fails
# Each role has 16 questions so we can always pick 8 unique ones
# ---------------------------------------------------------------------------

FALLBACK_QUESTIONS = {
    "Software Developer": [
        "Explain REST architecture and its constraints.",
        "What is dependency injection and why is it useful?",
        "Explain microservices vs monolithic architecture.",
        "What is database indexing and how does it improve performance?",
        "Difference between SQL and NoSQL databases?",
        "Explain caching strategies and when to use each.",
        "What is JWT authentication and how does it work?",
        "Explain the SOLID principles with examples.",
        "What is the difference between a process and a thread?",
        "Explain the CAP theorem.",
        "What is eventual consistency?",
        "How does garbage collection work?",
        "Explain design patterns: Singleton, Factory, Observer.",
        "What is a race condition and how do you prevent it?",
        "Explain the difference between synchronous and asynchronous code.",
        "What is a deadlock and how do you avoid it?",
    ],
    "Cyber Security Analyst": [
        "What is a SIEM and how is it used?",
        "Explain XSS and CSRF attacks with prevention.",
        "What is the OWASP Top 10?",
        "Explain brute force attack prevention techniques.",
        "What is privilege escalation?",
        "Difference between IDS and IPS?",
        "Explain Zero Trust security model.",
        "What is a SOC workflow?",
        "Explain SQL injection and how to prevent it.",
        "What is a man-in-the-middle attack?",
        "Explain public key infrastructure (PKI).",
        "What is a DDoS attack and mitigation strategies?",
        "Explain the principle of least privilege.",
        "What is threat modelling?",
        "Explain penetration testing methodology.",
        "What is a security audit?",
    ],
    "Data Analyst": [
        "Explain data normalisation.",
        "What is exploratory data analysis (EDA)?",
        "Difference between supervised and unsupervised learning?",
        "Explain data cleaning techniques.",
        "What is regression analysis?",
        "Explain SQL joins with examples.",
        "What are data visualisation best practices?",
        "Explain correlation vs causation.",
        "What is a data pipeline?",
        "Explain the difference between mean, median, and mode.",
        "What is a p-value in hypothesis testing?",
        "Explain outlier detection methods.",
        "What is feature scaling and why is it important?",
        "Explain the difference between OLAP and OLTP.",
        "What is a star schema in data warehousing?",
        "Explain time series analysis.",
    ],
    "AI / ML Engineer": [
        "Explain overfitting and underfitting with solutions.",
        "What is gradient descent and its variants?",
        "Difference between CNN and RNN architectures?",
        "Explain model evaluation metrics: precision, recall, F1.",
        "What is feature engineering?",
        "Explain bias vs variance tradeoff.",
        "What is transfer learning?",
        "Explain hyperparameter tuning strategies.",
        "What is the attention mechanism in transformers?",
        "Explain reinforcement learning.",
        "What is a confusion matrix?",
        "Explain dimensionality reduction techniques.",
        "What is cross-validation?",
        "Explain the difference between bagging and boosting.",
        "What is a generative adversarial network (GAN)?",
        "Explain model deployment and MLOps.",
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
        "What is GitOps?",
        "Explain the 12-factor app methodology.",
        "What is service mesh?",
        "Explain chaos engineering.",
        "What is a rolling deployment?",
        "Explain log aggregation strategies.",
        "What is a canary release?",
        "Explain infrastructure drift and how to prevent it.",
    ],
    "Cloud Engineer": [
        "Explain IAM in cloud platforms.",
        "What is auto scaling and how does it work?",
        "How does load balancing work?",
        "Explain VPC architecture.",
        "How do you secure cloud storage?",
        "Difference between IaaS, PaaS, and SaaS?",
        "Explain cloud cost optimisation strategies.",
        "How do you design high availability systems?",
        "What is a CDN and when would you use it?",
        "Explain serverless architecture.",
        "What is cloud-native development?",
        "Explain multi-region deployment strategies.",
        "What is a service level agreement (SLA)?",
        "Explain disaster recovery planning in the cloud.",
        "What is FinOps?",
        "Explain the shared responsibility model.",
    ],
    "Frontend Developer": [
        "What is the virtual DOM and how does React use it?",
        "Explain state management in React.",
        "How does browser rendering work?",
        "What is lazy loading and code splitting?",
        "Explain responsive design principles.",
        "How do you optimise frontend performance?",
        "What are web accessibility best practices?",
        "Explain CORS and how to handle it.",
        "What is the difference between SSR and CSR?",
        "Explain the event loop in JavaScript.",
        "What are Web Workers?",
        "Explain CSS specificity.",
        "What is a service worker?",
        "Explain the difference between cookies, localStorage, and sessionStorage.",
        "What is tree shaking in bundlers?",
        "Explain progressive web apps (PWA).",
    ],
    "Backend Engineer": [
        "Explain RESTful API design principles.",
        "How do you implement authentication in Django?",
        "What is database indexing and when should you use it?",
        "Explain caching strategies in backend systems.",
        "How would you design a scalable backend?",
        "What are message queues and when do you use them?",
        "Explain rate limiting implementation.",
        "How do you handle concurrency in backend systems?",
        "What is N+1 query problem and how do you fix it?",
        "Explain database transactions and ACID properties.",
        "What is connection pooling?",
        "Explain API versioning strategies.",
        "What is idempotency in APIs?",
        "Explain the difference between optimistic and pessimistic locking.",
        "What is a webhook?",
        "Explain GraphQL vs REST.",
    ],
    "Site Reliability Engineer": [
        "What is observability and its three pillars?",
        "Explain incident response workflow.",
        "How do you handle system outages?",
        "What is SLA, SLO, and SLI?",
        "Explain load testing strategies.",
        "How do you monitor microservices?",
        "What is root cause analysis?",
        "Explain reliability engineering principles.",
        "What is error budget?",
        "Explain toil and how to reduce it.",
        "What is a runbook?",
        "Explain distributed tracing.",
        "What is mean time to recovery (MTTR)?",
        "Explain capacity planning.",
        "What is a postmortem?",
        "Explain the difference between monitoring and alerting.",
    ],
    "Blockchain Developer": [
        "What is a smart contract?",
        "Explain consensus mechanisms: PoW vs PoS.",
        "What is gas in Ethereum?",
        "How do you secure a smart contract?",
        "Difference between public and private blockchain?",
        "Explain token standards like ERC-20 and ERC-721.",
        "What is Web3?",
        "How do you prevent reentrancy attacks?",
        "What is a DAO?",
        "Explain the Ethereum Virtual Machine (EVM).",
        "What is a flash loan attack?",
        "Explain IPFS and decentralised storage.",
        "What is a blockchain oracle?",
        "Explain layer 2 scaling solutions.",
        "What is a merkle tree?",
        "Explain the difference between fungible and non-fungible tokens.",
    ],
    "Product Data Scientist": [
        "Explain A/B testing methodology.",
        "How do you measure product success?",
        "What is cohort analysis?",
        "Explain hypothesis testing.",
        "How do you design experiments?",
        "What are business KPIs and how do you choose them?",
        "Explain churn prediction models.",
        "How do you communicate data insights to stakeholders?",
        "What is statistical significance?",
        "Explain funnel analysis.",
        "What is a north star metric?",
        "Explain causal inference.",
        "What is a holdout group?",
        "Explain multi-armed bandit testing.",
        "What is data-driven decision making?",
        "Explain the difference between correlation and causation in product context.",
    ],
    "Full Stack Web Developer": [
        "Explain how frontend and backend communicate.",
        "What is JWT authentication and how do you implement it?",
        "How would you design a scalable web application?",
        "Explain database normalisation.",
        "How do you deploy a web application?",
        "What is CORS and how do you handle it?",
        "Explain MVC architecture.",
        "How do you secure a web application?",
        "What is the difference between monolithic and microservices architecture?",
        "Explain WebSockets vs HTTP polling.",
        "What is server-side rendering?",
        "Explain database migrations.",
        "What is an ORM and what are its tradeoffs?",
        "Explain session management.",
        "What is a reverse proxy?",
        "Explain the difference between horizontal and vertical scaling.",
    ],
}

# Ensure every role has at least MAX_QUESTIONS entries
for _role_name, _qs in FALLBACK_QUESTIONS.items():
    assert len(_qs) >= MAX_QUESTIONS, (
        "Role '{}' has only {} questions (need {})".format(
            _role_name, len(_qs), MAX_QUESTIONS
        )
    )


# ---------------------------------------------------------------------------
# Question generation — guaranteed unique per session
# ---------------------------------------------------------------------------

def _pick_unique_questions(role, count, used_questions=None):
    # type: (object, int, Optional[List[str]]) -> List[str]
    """
    Returns `count` unique questions for the role.
    Avoids any question already in `used_questions`.
    """
    used = set(used_questions or [])
    pool = list(FALLBACK_QUESTIONS.get(
        role.name,
        random.choice(list(FALLBACK_QUESTIONS.values()))
    ))
    # Remove already-used questions
    available = [q for q in pool if q not in used]
    # If not enough available, reset (all questions exhausted)
    if len(available) < count:
        available = pool
    random.shuffle(available)
    return available[:count]


def generate_ai_questions_logic(role, count=8, used_questions=None):
    # type: (object, int, Optional[List[str]]) -> List[str]
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return _pick_unique_questions(role, count, used_questions)

    used = set(used_questions or [])

    # Prompt engineered for short, natural, conversational interview questions
    prompt = (
        "You are a technical interviewer at a top tech company.\n"
        "Generate {count} interview questions for a {role} candidate.\n\n"
        "STRICT RULES:\n"
        "- Each question must be SHORT — maximum 12 words\n"
        "- Sound like a real interviewer speaking naturally\n"
        "- One concept per question\n"
        "- No multi-part questions\n"
        "- No academic or essay-style prompts\n"
        "- Vary difficulty: start easy, get harder\n"
        "- Return ONLY a numbered list, nothing else\n\n"
        "GOOD examples:\n"
        "1. What is database indexing?\n"
        "2. How does rate limiting work?\n"
        "3. Explain connection pooling.\n"
        "4. What is idempotency in REST APIs?\n"
        "5. How would you prevent SQL injection?\n\n"
        "BAD examples (too long, too academic — DO NOT do this):\n"
        "- Describe the complete architecture of a distributed blockchain system...\n"
        "- Explain in detail how you would design a microservices platform...\n\n"
        "Now generate {count} short interview questions for: {role}"
    ).format(count=count, role=role.name)

    try:
        import httpx
        headers = {
            "Authorization": "Bearer {}".format(key),
            "Content-Type":  "application/json",
            "User-Agent":    "Mozilla/5.0 (compatible; AIMockInterview/1.0)",
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens":  400,
        }
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers
            )

        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            questions = []
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Strip numbering like "1." "1)" "-"
                line = re.sub(r"^\d+[\.\)\-]\s*", "", line).strip()
                # Skip lines that are clearly not questions (headers, etc.)
                if len(line) < 5 or len(line) > 120:
                    continue
                if line not in used:
                    questions.append(line)
            if len(questions) >= count:
                logger.info("[QUESTIONS] AI generated %d for %s", len(questions), role.name)
                return questions[:count]
            logger.warning("[QUESTIONS] AI returned %d, using fallback.", len(questions))
        else:
            logger.error("[QUESTIONS] HTTP %d: %.100s", resp.status_code, resp.text)

    except Exception as exc:
        logger.error("[QUESTIONS] Failed: %s", exc)

    return _pick_unique_questions(role, count, used_questions)


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
    keys_to_remove = [k for k in request.session.keys()
                      if k.startswith("interview_role_")]
    for key in keys_to_remove:
        request.session.pop(key, None)
    roles = JobRole.objects.all().order_by("name")
    return render(request, "select_role.html", {"roles": roles})


@never_cache
@login_required
def start_interview(request, role_id):
    role = JobRole.objects.get(id=role_id)
    session_key = "interview_role_{}".format(role_id)

    # Explicit restart — clear session and redirect cleanly
    if request.GET.get("restart") == "true":
        request.session.pop(session_key, None)
        return redirect("start_interview", role_id=role.id)

    # Initialise session
    if session_key not in request.session:
        questions = generate_ai_questions_logic(role, MAX_QUESTIONS)
        request.session[session_key] = {
            "question_number": 1,
            "questions":       questions,
            "used_questions":  list(questions),  # track for dedup on retake
            "total_score":     0,
            "answers":         [],
        }

    interview_data  = request.session[session_key]
    question_number = interview_data["question_number"]
    questions       = interview_data["questions"]

    # ---- Interview complete ----
    if question_number > MAX_QUESTIONS:
        total_raw  = interview_data["total_score"]
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

    # ---- POST — answer submitted ----
    if request.method == "POST":
        user_answer = request.POST.get("answer", "").strip()

        if not user_answer:
            return render(request, "interview.html", {
                "role":                role,
                "question":            question,
                "question_number":     question_number,
                "progress_percentage": int(((question_number - 1) / MAX_QUESTIONS) * 100),
                "error":               "Please write an answer before submitting.",
            })

        evaluation   = evaluate_answer(question=question,
                                       answer=user_answer,
                                       role=role.name)
        overall      = evaluation.get("overall_score", 0)
        display_score = round(overall / 10)

        # ── Smart XP: score-based, not time-based ──────────────────
        # score 0-2  → 0 XP  (gibberish / no answer)
        # score 3-4  → 5 XP  (weak)
        # score 5-6  → 15 XP (decent)
        # score 7-8  → 30 XP (strong)
        # score 9-10 → 50 XP (excellent)
        if display_score <= 2:
            xp_gained = 0
        elif display_score <= 4:
            xp_gained = 5
        elif display_score <= 6:
            xp_gained = 15
        elif display_score <= 8:
            xp_gained = 30
        else:
            xp_gained = 50

        # Streak bonus: 3+ consecutive answers scoring >= 7
        answers_so_far = interview_data.get("answers", [])
        streak = 0
        for prev in reversed(answers_so_far):
            if prev.get("score", 0) >= 7:
                streak += 1
            else:
                break
        streak_bonus = 0
        bonus_label  = ""
        if display_score >= 7:
            if streak >= 2:
                streak_bonus = 10
                bonus_label  = "🔥 Streak Bonus"
            if len(user_answer.split()) >= 60:
                streak_bonus += 5
                bonus_label   = "🧠 Deep Explanation" if not bonus_label else bonus_label

        xp_gained += streak_bonus

        interview_data["answers"].append({
            "question":    question,
            "user_answer": user_answer,
            "score":       display_score,
            "feedback":    evaluation.get("feedback", ""),
            "xp_gained":   xp_gained,
            "bonus_label": bonus_label,
        })

        interview_data["total_score"]     += overall
        interview_data["question_number"] += 1
        request.session[session_key]       = interview_data
        return redirect(request.path)

    # ---- GET — show question ----
    progress = int(((question_number - 1) / MAX_QUESTIONS) * 100)

    # XP earned so far — sum actual per-answer XP stored in session
    answers_list = interview_data.get("answers", [])
    xp_so_far    = sum(a.get("xp_gained", 0) for a in answers_list)

    # Last answer's XP gain — shown as burst on this page load
    last_xp       = 0
    last_bonus    = ""
    last_score    = -1
    if answers_list:
        last       = answers_list[-1]
        last_xp    = last.get("xp_gained", 0)
        last_bonus = last.get("bonus_label", "")
        last_score = last.get("score", -1)

    # Rank based on total XP
    if xp_so_far >= 200:
        rank = "Expert Engineer"
    elif xp_so_far >= 120:
        rank = "Interview Pro"
    elif xp_so_far >= 60:
        rank = "Skilled Candidate"
    elif xp_so_far >= 20:
        rank = "Explorer"
    else:
        rank = "Beginner"

    return render(request, "interview.html", {
        "role":                role,
        "question":            question,
        "question_number":     question_number,
        "progress_percentage": progress,
        "max_questions":       MAX_QUESTIONS,
        "xp_so_far":           xp_so_far,
        "last_xp":             last_xp,
        "last_bonus":          last_bonus,
        "last_score":          last_score,
        "rank":                rank,
    })


@login_required
def interview_result(request, session_id):
    session = InterviewSession.objects.get(id=session_id, user=request.user)
    answers = session.answer_set.all()
    # Pre-compute SVG ring offset: circumference = 2*pi*56 = 351.9
    circumference = 351.9
    ring_offset = round(circumference - (session.total_score / 100) * circumference, 1)
    # XP earned: sum actual per-answer XP from session answers
    # Session is already cleared, so derive from score-based formula
    xp_earned = 0
    for ans in answers:
        s = ans.score
        if s <= 2:
            xp_earned += 0
        elif s <= 4:
            xp_earned += 5
        elif s <= 6:
            xp_earned += 15
        elif s <= 8:
            xp_earned += 30
        else:
            xp_earned += 50
    return render(request, "result.html", {
        "role":        session.job_role,
        "session":     session,
        "percentage":  session.total_score,
        "answers":     answers,
        "ring_offset": ring_offset,
        "xp_earned":   xp_earned,
    })


def generate_ai_question(request):
    role_name = request.GET.get("role", "Software Developer")
    try:
        role = JobRole.objects.get(name=role_name)
    except JobRole.DoesNotExist:
        return JsonResponse({"questions": FALLBACK_QUESTIONS["Software Developer"]})
    questions = generate_ai_questions_logic(role)
    return JsonResponse({"questions": questions})


def ai_status(request):
    """Diagnostic — visit /interview/api/status/ to verify Groq is working."""
    import os
    key = os.environ.get("GROQ_API_KEY", "").strip()

    if not key:
        return JsonResponse({
            "groq_key_set": False,
            "status": "ERROR — GROQ_API_KEY not set in Render environment",
        })

    key_preview   = key[:8] + "..." + key[-4:]
    api_result    = "not_tested"
    api_error     = None

    try:
        import httpx
        headers = {
            "Authorization": "Bearer {}".format(key),
            "Content-Type":  "application/json",
            "User-Agent":    "Mozilla/5.0 (compatible; AIMockInterview/1.0)",
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "Reply with one word: working"}],
            "max_tokens": 10, "temperature": 0,
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers
            )
        if resp.status_code == 200:
            api_result = resp.json()["choices"][0]["message"]["content"].strip()
        else:
            api_error  = "HTTP {}: {}".format(resp.status_code, resp.text[:200])
            api_result = "failed"
    except Exception as exc:
        api_error  = "{}: {}".format(type(exc).__name__, str(exc))
        api_result = "failed"

    return JsonResponse({
        "groq_key_set":       True,
        "groq_key_preview":   key_preview,
        "groq_key_format_ok": key.startswith("gsk_"),
        "groq_api_test":      api_result,
        "groq_api_error":     api_error,
        "method":             "httpx_direct",
        "status":             "OK" if api_result not in ("failed","not_tested") else "ERROR",
    })
