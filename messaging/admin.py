from django.contrib import admin

from .models import Conversation, Message


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(ReadOnlyAdmin):
    list_display = ('subject', 'kind', 'technician', 'created_by', 'last_message_at')
    list_filter = ('kind',)
    search_fields = ('subject', 'technician__username')


@admin.register(Message)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ('conversation', 'sender', 'created_at')