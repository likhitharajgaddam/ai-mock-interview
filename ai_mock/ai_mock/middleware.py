from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from datetime import timedelta


class AutoLogoutMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        if request.user.is_authenticated:
            now = timezone.now()

            if 'last_activity' in request.session:
                last_activity = request.session['last_activity']

                if now - timezone.datetime.fromisoformat(last_activity) > timedelta(minutes=10):
                    logout(request)
                    return redirect('login')

            request.session['last_activity'] = now.isoformat()

        response = self.get_response(request)
        return response