from django.shortcuts import render, redirect
from .models import JobRole, InterviewSession, Answer
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Avg
import json
import os
import random
from django.views.decorators.cache import never_cache
from groq import Groq

MAX_QUESTIONS = 8
FALLBACK_QUESTIONS = {

    "Software Developer": [
        "Explain REST architecture.",
        "What is dependency injection?",
        "Explain microservices architecture.",
        "What is database indexing?",
        "Difference between SQL and NoSQL?",
        "Explain caching strategies.",
        "What is JWT authentication?",
        "Explain SOLID principles."
    ],

    "Cyber Security Analyst": [
        "What is a SIEM?",
        "Explain XSS and CSRF.",
        "What is OWASP Top 10?",
        "Explain brute force attack prevention.",
        "What is privilege escalation?",
        "Difference between IDS and IPS?",
        "Explain Zero Trust security.",
        "What is a SOC workflow?"
    ],

    "Data Analyst": [
        "Explain data normalization.",
        "What is EDA?",
        "Difference between supervised and unsupervised learning?",
        "Explain data cleaning techniques.",
        "What is regression analysis?",
        "Explain SQL joins.",
        "What is data visualization best practice?",
        "Explain correlation vs causation."
    ],

    "AI / ML Engineer": [
        "Explain overfitting and underfitting.",
        "What is gradient descent?",
        "Difference between CNN and RNN?",
        "Explain model evaluation metrics.",
        "What is feature engineering?",
        "Explain bias vs variance.",
        "What is transfer learning?",
        "Explain hyperparameter tuning."
    ],

    "DevOps Engineer": [
        "Explain CI/CD pipeline design.",
        "What is Infrastructure as Code?",
        "How does Docker differ from virtual machines?",
        "Explain Kubernetes architecture.",
        "What is blue-green deployment?",
        "How do you monitor distributed systems?",
        "Explain container orchestration.",
        "How would you secure a CI/CD pipeline?"
    ],

    "Cloud Engineer": [
        "Explain IAM in cloud platforms.",
        "What is auto scaling?",
        "How does load balancing work?",
        "Explain VPC architecture.",
        "How do you secure cloud storage?",
        "Difference between IaaS, PaaS, and SaaS?",
        "Explain cloud cost optimization strategies.",
        "How do you design high availability systems?"
    ],

    "Frontend Developer": [
        "What is virtual DOM?",
        "Explain state management in React.",
        "How does browser rendering work?",
        "What is lazy loading?",
        "Explain responsive design principles.",
        "How do you optimize frontend performance?",
        "What are web accessibility best practices?",
        "Explain CORS."
    ],

    "Backend Engineer": [
        "Explain RESTful API design principles.",
        "How do you implement authentication in Django?",
        "What is database indexing?",
        "Explain caching in backend systems.",
        "How would you design a scalable backend?",
        "What are message queues?",
        "Explain rate limiting.",
        "How do you handle concurrency?"
    ],

    "Site Reliability Engineer": [
        "What is observability?",
        "Explain incident response workflow.",
        "How do you handle system outages?",
        "What is SLA, SLO, and SLI?",
        "Explain load testing.",
        "How do you monitor microservices?",
        "What is root cause analysis?",
        "Explain reliability engineering principles."
    ],

    "Blockchain Developer": [
        "What is a smart contract?",
        "Explain consensus mechanisms.",
        "What is gas in Ethereum?",
        "How do you secure a smart contract?",
        "Difference between public and private blockchain?",
        "Explain token standards like ERC-20.",
        "What is Web3?",
        "How do you prevent reentrancy attacks?"
    ],

    "Product Data Scientist": [
        "Explain A/B testing.",
        "How do you measure product success?",
        "What is cohort analysis?",
        "Explain hypothesis testing.",
        "How do you design experiments?",
        "What are business KPIs?",
        "Explain churn prediction.",
        "How do you communicate data insights?"
    ],

    "Full Stack Web Developer": [
        "Explain how frontend and backend communicate.",
        "What is JWT authentication?",
        "How would you design a scalable web app?",
        "Explain database normalization.",
        "How do you deploy a web application?",
        "What is CORS?",
        "Explain MVC architecture.",
        "How do you secure a web application?"
    ],
}

groq_api_key = os.environ.get("GROQ_API_KEY", "")
groq_client = Groq(api_key=groq_api_key)




def generate_ai_question(request):
    return JsonResponse({"message": "API working"})

    prompt = f"""
Generate {count} different advanced technical interview questions.

Role: {role.name}
Description: {role.description}

Return only numbered questions.
"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.9
        )

        text = response.choices[0].message.content.strip()

        questions = []
        for line in text.split("\n"):
            line = line.strip()
            if line:
                line = line.split(". ", 1)[-1]
                questions.append(line)

        return questions[:count]

    except Exception as e:
        print("Groq Error:", e)
        return FALLBACK_QUESTIONS.get(role.name, random.choice(list(FALLBACK_QUESTIONS.values())))
    


@never_cache
@login_required
def select_role(request):

    # Clear ALL interview sessions when coming to role selection
    keys_to_remove = [key for key in request.session.keys() if key.startswith("interview_role_")]

    for key in keys_to_remove:
        request.session.pop(key, None)

    roles = JobRole.objects.all()
    return render(request, 'select_role.html', {'roles': roles})


def ai_next_step(role, conversation_history):
    try:
        prompt = f"""
You are a professional technical interviewer for the role: {role.name}

Conversation so far:
{conversation_history}

Ask the next technical question.
"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print("Groq Conversation Error:", e)
        return "INTERVIEW_COMPLETE"

@never_cache
@login_required
def start_interview(request, role_id):

    role = JobRole.objects.get(id=role_id)
    session_key = f"interview_role_{role_id}"

    # Restart only if explicitly requested
    if request.GET.get("restart") == "true":
        request.session.pop(session_key, None)
        return redirect("start_interview", role_id=role.id)

    # Initialize only if session doesn't exist
    if session_key not in request.session:
        try:
            questions = generate_ai_questions_logic(role, MAX_QUESTIONS)
            random.shuffle(questions)
        except Exception:
            questions = FALLBACK_QUESTIONS.get(
                role.name,
                FALLBACK_QUESTIONS["Software Developer"]
            )
            random.shuffle(questions)

        request.session[session_key] = {
            "question_number": 1,
            "questions": questions,
            "total_score": 0,
            "answers": []
        }

    interview_data = request.session[session_key]
    question_number = interview_data["question_number"]
    questions = interview_data["questions"]

    # Finish interview
    if question_number > MAX_QUESTIONS:

        total_score = interview_data["total_score"]
        percentage = int((total_score / (MAX_QUESTIONS * 10)) * 100)

        interview_session = InterviewSession.objects.create(
            user=request.user,
            job_role=role,
            total_score=percentage
        )

        for ans in interview_data["answers"]:
            Answer.objects.create(
                session=interview_session,
                question_text=ans["question"],
                response=ans["user_answer"],
                score=ans["score"],
                feedback=ans["feedback"]
            )

        request.session.pop(session_key, None)

        return redirect("interview_result", session_id=interview_session.id)

    question = questions[question_number - 1]

    if request.method == "POST":

        user_answer = request.POST.get("answer")

        if not user_answer:
            return render(request, "interview.html", {
                "role": role,
                "question": question,
                "question_number": question_number,
                "progress_percentage": int(((question_number-1)/MAX_QUESTIONS)*100),
                "error": "Please answer before submitting."
            })

        score, feedback = evaluate_answer_with_ai(
            question,
            user_answer,
            role.name,
            request.session.get("last_answer")
        )

        interview_data["answers"].append({
            "question": question,
            "user_answer": user_answer,
            "score": score,
            "feedback": feedback
        })

        interview_data["total_score"] += score
        interview_data["question_number"] += 1

        request.session["last_answer"] = user_answer
        request.session[session_key] = interview_data

        return redirect(request.path)

    progress_percentage = int(((question_number - 1) / MAX_QUESTIONS) * 100)

    return render(request, "interview.html", {
        "role": role,
        "question": question,
        "question_number": question_number,
        "progress_percentage": progress_percentage
    })


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {'form': form})



def evaluate_answer_with_ai(question_text, user_answer, role_name, last_answer):

    try:
        prompt = f"""
You are a STRICT senior technical interviewer.

If the answer is incomplete, vague, off-topic, or less than 2 meaningful sentences,
you MUST give 0 to 3 score.

If the answer is a single sentence or generic like "using django",
you MUST give 0.

Role: {role_name}

Question:
{question_text}

Answer:
{user_answer}

Be strict and realistic like a FAANG interviewer.

Return exactly:

Score: X/10
Feedback: short explanation.
"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )

        text = response.choices[0].message.content

        import re
        match = re.search(r"(\d+)/10", text)

        if match:
            score = int(match.group(1))
        else:
            score = 5

        feedback_match = re.search(r"Feedback:\s*(.*)", text, re.DOTALL)
        feedback = feedback_match.group(1).strip() if feedback_match else "Answer evaluated."

        return score, feedback

    except Exception as e:
        print("Groq Scoring Error:", e)
        return 5, "Fallback evaluation."
    

from django.shortcuts import render, redirect


def home(request):
    if request.user.is_authenticated:
        return redirect('select_role')  

    return render(request, 'home.html') 

def about(request):
    return render(request, "about.html")



@login_required
def interview_result(request, session_id):
    session = InterviewSession.objects.get(id=session_id, user=request.user)
    answers = session.answer_set.all()

    return render(request, "result.html", {
        "role": session.job_role,
        "percentage": session.total_score,
        "answers": answers
    })