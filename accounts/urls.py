from . import views
from django.contrib.auth.views import LogoutView
from django.urls import path


urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.RoleLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('operator/', views.operator_home, name='operator_home'),
    path('support/', views.support_dashboard, name='support_dashboard'),
]