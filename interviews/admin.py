from django.contrib import admin
from .models import JobRole, InterviewSession, Answer


@admin.register(JobRole)
class JobRoleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    list_display_links = ('name',)


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'job_role', 'total_score', 'created_at')
    list_filter = ('job_role',)
    search_fields = ('user__username',)


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'score')