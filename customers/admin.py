from django.contrib import admin

from .models import City, Customer


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('subscription_id', 'full_name', 'mobile', 'city', 'center', 'registered_at')
    search_fields = ('subscription_id', 'full_name', 'mobile')
    list_filter = ('city',)