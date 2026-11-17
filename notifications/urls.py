from django.urls import path

from . import views

urlpatterns = [
    path('notifications/panel/', views.panel, name='notification_panel'),
    path('notifications/read-all/', views.mark_all_read, name='notification_read_all'),
    path('notifications/<int:pk>/read/', views.mark_read, name='notification_read'),
    path('notifications/<int:pk>/open/', views.open_notification, name='notification_open'),
]