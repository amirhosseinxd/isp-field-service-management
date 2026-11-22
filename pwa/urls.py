from django.urls import path

from . import views

urlpatterns = [
    path('manifest.webmanifest', views.manifest, name='pwa_manifest'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('pwa/icon-<int:size>.png', views.icon, name='pwa_icon'),
    path('offline/', views.offline, name='pwa_offline'),
    path('install/', views.install_help, name='pwa_install'),
]