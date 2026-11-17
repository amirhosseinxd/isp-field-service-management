from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'recipient', 'kind', 'job', 'read_at', 'resolved_at')
    list_filter = ('kind',)