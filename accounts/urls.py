from . import views
from django.contrib.auth.views import LogoutView
from django.urls import path


urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.RoleLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
]