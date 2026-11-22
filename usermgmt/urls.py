from django.urls import path

from . import views

urlpatterns = [
    path('support/users/', views.user_list, name='user_list'),
    path('support/users/new/', views.user_create, name='user_create'),
    path('support/users/<int:pk>/', views.user_edit, name='user_edit'),
    path('support/users/<int:pk>/active/', views.user_set_active, name='user_set_active'),
    path('support/users/<int:pk>/password/', views.user_set_password, name='user_set_password'),
]