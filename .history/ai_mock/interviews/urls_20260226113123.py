from django.urls import path
from . import views

urlpatterns = [
    path('', views.select_role, name='select_role'),  # /interview/
    path('start/<int:role_id>/', views.start_interview, name='start_interview'),
    path('about/', views.about, name='about'),
    path("result/<int:session_id>/", views.interview_result, name="interview_result"),
]