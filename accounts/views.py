from django.shortcuts import render
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from .models import User
from .permissions import role_required
from django.urls import reverse



def home_name_for(user):
    """Name of the landing page for this user's role."""
    if user.role == User.Role.ADMIN:
        return 'support_dashboard'
    return 'operator_home'


class RoleLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        # Honour ?next=... if present, otherwise go to the role's home
        return self.get_redirect_url() or reverse(home_name_for(self.request.user))


@login_required
def home(request):
    return redirect(home_name_for(request.user))
