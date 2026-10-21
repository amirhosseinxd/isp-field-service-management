from django.urls import path
from . import views




urlpatterns = [
    path('operator/', views.operator_home, name='operator_home'),
    path('jobs/<int:pk>/', views.job_start, name='job_start'),
    path('jobs/<int:pk>/location/', views.job_location, name='job_location'),
    path('jobs/<int:pk>/photos/<str:stage>/', views.job_photos, name='job_photos'),
    path('jobs/<int:pk>/report/', views.job_report, name='job_report'),
]