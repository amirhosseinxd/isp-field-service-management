from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

# Register your models here.



@admin.register(User)
class CustomUserAdmin(UserAdmin):
    def has_delete_permission(self, request, obj=None):
        return False   # accounts are deactivated, never deleted
    fieldsets = UserAdmin.fieldsets + (
        ('Field service', {'fields': ('role', 'phone')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Field service', {'fields': ('role', 'phone')}),
    )
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active')