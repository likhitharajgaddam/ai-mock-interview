from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('session/<int:session_id>/', views.session_detail, name='session_detail'),
]