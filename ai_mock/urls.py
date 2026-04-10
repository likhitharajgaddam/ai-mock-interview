from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from interviews.views import register, home

urlpatterns = [
    path('admin/', admin.site.urls),

    # Public Pages
    path('', home, name='home'),   # 👈 DEFAULT = HOME
    path('login/', auth_views.LoginView.as_view(
        template_name='login.html',
        redirect_authenticated_user=True
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('register/', register, name='register'),

    # Apps
    path('interview/', include('interviews.urls')),
    path('dashboard/', include('dashboard.urls')),
]