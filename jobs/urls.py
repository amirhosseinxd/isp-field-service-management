from django.urls import path
from . import views




urlpatterns = [
    # Operator
    path('operator/', views.operator_home, name='operator_home'),
    path('jobs/<int:pk>/', views.job_start, name='job_start'),
    path('jobs/<int:pk>/location/', views.job_location, name='job_location'),
    path('jobs/<int:pk>/photos/<str:stage>/', views.job_photos, name='job_photos'),
    path('jobs/<int:pk>/report/', views.job_report, name='job_report'),
    path('jobs/<int:pk>/photos/<int:photo_pk>/delete/', views.job_photo_delete, name='job_photo_delete'),
    path('jobs/<int:pk>/step/<int:index>/', views.job_step, name='job_step'),
    path('jobs/<int:pk>/step/<int:index>/evidence/<int:evidence_pk>/delete/',
         views.job_evidence_delete, name='job_evidence_delete'),

    # Support
    path('support/', views.support_dashboard, name='support_dashboard'),
    path('support/jobs/<int:pk>/', views.support_job_detail, name='support_job_detail'),
    path('support/jobs/<int:pk>/review/', views.support_job_review, name='support_job_review'),
    path('support/photos/', views.photo_history, name='photo_history'),
    path('support/jobs/new/', views.job_create, name='job_create'),
    path('support/jobs/<int:pk>/return/', views.job_return, name='job_return'),


    # Protected photo + video files (admins + the job's operator)
    path('photos/<int:pk>/file/', views.job_photo, name='photo_file'),
    path('videos/<int:pk>/file/', views.job_video, name='video_file'),
]