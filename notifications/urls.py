from django.urls import path

from . import views

urlpatterns = [
    path('notifications/panel/', views.panel, name='notification_panel'),
    path('notifications/read-all/', views.mark_all_read, name='notification_read_all'),
    path('notifications/<int:pk>/read/', views.mark_read, name='notification_read'),
    path('notifications/<int:pk>/open/', views.open_notification, name='notification_open'),
    path('notifications/push/subscribe/', views.push_subscribe, name='push_subscribe'),
    path('notifications/push/unsubscribe/', views.push_unsubscribe, name='push_unsubscribe'),
    path('sw.js', views.service_worker, name='service_worker'),
]