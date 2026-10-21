from django.urls import path
from . import views




urlpatterns = [
    # Operator
    path('operator/', views.operator_home, name='operator_home'),
    path('jobs/<int:pk>/', views.job_start, name='job_start'),
    path('jobs/<int:pk>/location/', views.job_location, name='job_location'),
    path('jobs/<int:pk>/photos/<str:stage>/', views.job_photos, name='job_photos'),
    path('jobs/<int:pk>/report/', views.job_report, name='job_report'),

    # Support
    path('support/', views.support_dashboard, name='support_dashboard'),
    path('support/jobs/<int:pk>/', views.support_job_detail, name='support_job_detail'),
    path('support/jobs/<int:pk>/review/', views.support_job_review, name='support_job_review'),
    path('support/photos/', views.photo_history, name='photo_history'),

    # Protected photo files (admins + the job's operator)
    path('photos/<int:pk>/file/', views.job_photo, name='photo_file'),
]