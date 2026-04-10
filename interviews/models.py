from django.db import models
from django.contrib.auth.models import User

class JobRole(models.Model):
  name = models.CharField(max_length=100)
  description = models.TextField()
  skills_required = models.TextField(blank=True, null=True)


  def __str__(self):
    return self.name
  

class Question(models.Model):
  job_role = models.ForeignKey(JobRole, on_delete = models.CASCADE)
  text = models.TextField()
  topic = models.CharField(max_length = 100)

  def __str__(self):
    return self.text[:50]
  

class InterviewSession(models.Model):
  user = models.ForeignKey(User, on_delete = models.CASCADE)
  job_role = models. ForeignKey(JobRole, on_delete = models.CASCADE)
  created_at = models.DateTimeField(auto_now_add = True)
  total_score = models.IntegerField(default = 0)

  def __str__(self):
    return f"{self.user.username} - {self.job_role.name}"


class Answer(models.Model):
  session = models.ForeignKey(InterviewSession, on_delete = models.CASCADE)
  question_text = models.TextField()
  response = models.TextField()
  score = models.IntegerField(default = 0)
  feedback = models.TextField(blank = True)

  def __str__(self):
    return f"{self.question_text[:30]}"



# Create your models here.
