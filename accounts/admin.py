from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

# Register your models here.



@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Field service', {'fields': ('role', 'phone')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Field service', {'fields': ('role', 'phone')}),
    )
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active')