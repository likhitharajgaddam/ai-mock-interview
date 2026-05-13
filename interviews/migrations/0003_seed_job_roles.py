"""
Data migration — seeds default JobRole records.

Safe to run multiple times (uses get_or_create).
Runs automatically during: python manage.py migrate
"""

from django.db import migrations

JOB_ROLES = [
    {
        "name": "Software Developer",
        "description": (
            "Design, build and maintain software applications. "
            "Covers algorithms, data structures, system design and clean code."
        ),
        "skills_required": "Python, Java, C++, Data Structures, Algorithms, System Design",
    },
    {
        "name": "Frontend Developer",
        "description": (
            "Build responsive, accessible user interfaces for web applications. "
            "Covers HTML, CSS, JavaScript, React and browser performance."
        ),
        "skills_required": "HTML, CSS, JavaScript, React, TypeScript, Web Performance",
    },
    {
        "name": "Backend Engineer",
        "description": (
            "Design and implement server-side logic, APIs and databases. "
            "Covers REST, authentication, caching and scalability."
        ),
        "skills_required": "Django, Node.js, REST APIs, PostgreSQL, Redis, Authentication",
    },
    {
        "name": "Full Stack Web Developer",
        "description": (
            "Work across the entire web stack from database to UI. "
            "Covers frontend frameworks, backend APIs and deployment."
        ),
        "skills_required": "React, Django, PostgreSQL, REST APIs, Docker, CI/CD",
    },
    {
        "name": "AI / ML Engineer",
        "description": (
            "Build and deploy machine learning models and AI systems. "
            "Covers model training, evaluation, MLOps and deep learning."
        ),
        "skills_required": "Python, TensorFlow, PyTorch, Scikit-learn, MLOps, Statistics",
    },
    {
        "name": "Data Analyst",
        "description": (
            "Analyse data to extract business insights and drive decisions. "
            "Covers SQL, statistics, visualisation and reporting."
        ),
        "skills_required": "SQL, Python, Pandas, Tableau, Statistics, Data Visualisation",
    },
    {
        "name": "Cyber Security Analyst",
        "description": (
            "Protect systems and networks from threats and vulnerabilities. "
            "Covers OWASP, penetration testing, incident response and SIEM."
        ),
        "skills_required": "Network Security, OWASP, Penetration Testing, SIEM, Incident Response",
    },
    {
        "name": "DevOps Engineer",
        "description": (
            "Automate infrastructure, CI/CD pipelines and system reliability. "
            "Covers Docker, Kubernetes, Terraform and monitoring."
        ),
        "skills_required": "Docker, Kubernetes, Terraform, CI/CD, Linux, Monitoring",
    },
    {
        "name": "Cloud Engineer",
        "description": (
            "Design and manage cloud infrastructure on AWS, GCP or Azure. "
            "Covers IAM, networking, auto-scaling and cost optimisation."
        ),
        "skills_required": "AWS, GCP, Azure, Terraform, Networking, IAM, Cost Optimisation",
    },
    {
        "name": "Site Reliability Engineer",
        "description": (
            "Ensure reliability, scalability and performance of production systems. "
            "Covers SLOs, incident management, observability and on-call."
        ),
        "skills_required": "SLO/SLI/SLA, Observability, Incident Management, Linux, Automation",
    },
    {
        "name": "Product Data Scientist",
        "description": (
            "Apply statistical analysis and ML to product and business problems. "
            "Covers A/B testing, experimentation, cohort analysis and KPIs."
        ),
        "skills_required": "Python, Statistics, A/B Testing, SQL, Machine Learning, Experimentation",
    },
    {
        "name": "Blockchain Developer",
        "description": (
            "Build decentralised applications and smart contracts. "
            "Covers Solidity, Ethereum, Web3, consensus mechanisms and security."
        ),
        "skills_required": "Solidity, Ethereum, Web3.js, Smart Contracts, DeFi, Security",
    },
]


def seed_job_roles(apps, schema_editor):
    JobRole = apps.get_model("interviews", "JobRole")
    created_count = 0
    for role_data in JOB_ROLES:
        _, created = JobRole.objects.get_or_create(
            name=role_data["name"],
            defaults={
                "description": role_data["description"],
                "skills_required": role_data["skills_required"],
            },
        )
        if created:
            created_count += 1
    print(
        "\n  Seeded {} new JobRole(s). "
        "{} already existed.".format(created_count, len(JOB_ROLES) - created_count)
    )


def unseed_job_roles(apps, schema_editor):
    # Reverse migration — only removes roles that have no sessions attached
    JobRole = apps.get_model("interviews", "JobRole")
    names = [r["name"] for r in JOB_ROLES]
    JobRole.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("interviews", "0002_jobrole_skills_required"),
    ]

    operations = [
        migrations.RunPython(seed_job_roles, reverse_code=unseed_job_roles),
    ]
