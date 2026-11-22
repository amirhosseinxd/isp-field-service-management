from django.conf import settings
from django.db import models
from django.urls import reverse


class AuditEntry(models.Model):
    class Action(models.TextChoices):
        JOB_CREATED = 'job_created', 'ایجاد و ارجاع کار'
        JOB_SUBMITTED = 'job_submitted', 'ارسال کار'
        JOB_RETURNED = 'job_returned', 'برگشت کار برای اصلاح'
        JOB_REVIEWED = 'job_reviewed', 'بررسی کار'
        EVIDENCE_DELETED = 'evidence_deleted', 'حذف عکس یا ویدیو'
        CUSTOMER_CREATED = 'customer_created', 'ثبت مشترک'
        CUSTOMER_UPDATED = 'customer_updated', 'ویرایش مشترک'
        CUSTOMER_IMPORT = 'customer_import', 'ورود مشترکین از اکسل'
        LOGIN = 'login', 'ورود موفق'
        LOGIN_FAILED = 'login_failed', 'ورود ناموفق'
        USER_CREATED = 'user_created', 'ایجاد حساب کاربری'
        USER_UPDATED = 'user_updated', 'ویرایش حساب کاربری'
        USER_DEACTIVATED = 'user_deactivated', 'غیرفعال‌سازی حساب'
        USER_ACTIVATED = 'user_activated', 'فعال‌سازی حساب'
        USER_PASSWORD_RESET = 'user_password_reset', 'تغییر رمز عبور'
        USER_ROLE_CHANGED = 'user_role_changed', 'تغییر نقش حساب'
        USER_ACCESS_CHANGED = 'user_access_changed', 'تغییر دسترسی مدیریت حساب‌ها'

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='audit_entries',
    )
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    target_type = models.CharField(max_length=30, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name_plural = 'audit entries'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('رکوردهای گزارش تغییرات قابل ویرایش نیستند.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('رکوردهای گزارش تغییرات قابل حذف نیستند.')

    def target_url(self):
        if self.target_id is None:
            return ''
        if self.target_type == 'job':
            return reverse('support_job_detail', args=[self.target_id])
        if self.target_type == 'customer':
            return reverse('customer_detail', args=[self.target_id])
        return ''