from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('', include('jobs.urls')),
    path('', include('customers.urls')),
    path('', include('audit.urls')),
    path('', include('notifications.urls')),
    path('', include('pwa.urls')),
    path('', include('usermgmt.urls')),
    path('', include('messaging.urls')),
]
