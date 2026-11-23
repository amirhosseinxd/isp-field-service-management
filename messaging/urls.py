from django.urls import path

from . import views

urlpatterns = [
    path('messages/', views.inbox, name='inbox'),
    path('messages/new/', views.compose, name='message_new'),
    path('messages/read-all/', views.mark_all_read, name='messages_read_all'),
    path('messages/unread/', views.unread_json, name='messages_unread'),
    path('messages/<int:pk>/', views.conversation, name='conversation'),
]