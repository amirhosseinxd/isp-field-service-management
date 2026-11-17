from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.core.validators import MinValueValidator


from audit.models import AuditEntry
from audit.services import log as audit_log

class Job(models.Model):
    class JobType(models.TextChoices):
        INSTALLATION = 'installation', 'نصب'
        REPAIR = 'repair', 'تعمیر'
        MALFUNCTION_REPAIR = 'malfunction_repair', 'رفع خرابی'


    


    class Workflow(models.TextChoices):
        FTTH_INQUIRY = 'ftth_inquiry', 'امکان‌سنجی'
        DROP_CABLE = 'drop_cable', 'دراپ کشی'
        FUSION = 'fusion', 'فیوژن'
        SERVICE_DELIVERY = 'service_delivery', 'تحویل سرویس'
        MALFUNCTION = 'malfunction', 'رفع خرابی'

    




    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'ارجاع شده'
        IN_PROGRESS = 'in_progress', 'در حال انجام'
        SUBMITTED = 'submitted', 'ارسال شده'
        RETURNED = 'returned', 'برگشت داده شده'
        REVIEWED = 'reviewed', 'بررسی شده'



    class FtthOutcome(models.TextChoices):
        FEASIBLE = 'feasible', 'بله — امکان‌پذیر'
        UNFEASIBLE = 'unfeasible', 'خیر — غیرقابل انجام'
        NEEDS_MATERIALS = 'needs_materials', 'نیاز به متریال دارد'

    VALID_WORKFLOWS = {
        JobType.INSTALLATION: [
            Workflow.FTTH_INQUIRY, Workflow.DROP_CABLE,
            Workflow.FUSION, Workflow.SERVICE_DELIVERY,
        ],
        JobType.REPAIR: [
            Workflow.DROP_CABLE, Workflow.FUSION, Workflow.SERVICE_DELIVERY,
        ],
        JobType.MALFUNCTION_REPAIR: [Workflow.MALFUNCTION],
    }

    class LocationSource(models.TextChoices):
        GPS = 'gps', 'GPS'
        MANUAL = 'manual', 'دستی'

    location_source = models.CharField(
        max_length=10, choices=LocationSource.choices, blank=True,
    )

    job_type = models.CharField(max_length=20, choices=JobType.choices)
    workflow = models.CharField(max_length=30, choices=Workflow.choices)
    assigned_operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='jobs',
        limit_choices_to={'role': 'operator'},
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='jobs_created',
    )


    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT,
        null=True, blank=True, related_name='jobs',
    )

    
    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='jobs_reviewed',
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

        # Answers given by the technician. Empty / null means "not answered yet".
    ftth_outcome = models.CharField(max_length=20, choices=FtthOutcome.choices, blank=True)
    fat_needs_splitter = models.BooleanField(null=True, blank=True)
    tokar_used = models.BooleanField(null=True, blank=True)
    materials_used = models.BooleanField(null=True, blank=True)
    upload_mbps = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    download_mbps = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                name='job_valid_workflow_for_type',
                condition=(
                    models.Q(
                        job_type='installation',
                        workflow__in=['ftth_inquiry', 'drop_cable', 'fusion', 'service_delivery'],
                    )
                    | models.Q(
                        job_type='repair',
                        workflow__in=['drop_cable', 'fusion', 'service_delivery'],
                    )
                    | models.Q(job_type='malfunction_repair', workflow='malfunction')
                ),
            ),
        ]

    def __str__(self):
        return f"Job #{self.pk} - {self.get_job_type_display()} / {self.get_workflow_display()}"

    def clean(self):
        super().clean()
        allowed = self.VALID_WORKFLOWS.get(self.job_type, [])
        if self.workflow and self.workflow not in allowed:
            raise ValidationError({'workflow': 'این نوع کار برای دسته انتخاب‌شده مجاز نیست.'})

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            # A partial save only writes the listed fields, so add this one to the list
            kwargs['update_fields'] = {*update_fields, 'updated_at'}
        super().save(*args, **kwargs)

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    

    @transaction.atomic
    def submit(self, user, description):
        # Imported here, not at the top of the file: workflows.py imports this module,
        # and a top-level import in both files would loop forever.
        from . import workflows

        if self.assigned_operator_id != user.id:
            raise PermissionError('فقط تکنسین تخصیص‌یافته می‌تواند این کار را ارسال کند.')
        if self.status in (self.Status.SUBMITTED, self.Status.REVIEWED):
            raise ValueError('این کار قبلاً ارسال شده است.')
        if not description.strip():
            raise ValueError('توضیحات کار الزامی است.')

        # Save the report first, so the registry's description check passes
        report, _ = WorkReport.objects.update_or_create(
            job=self,
            defaults={'description': description.strip(), 'submitted_by': user},
        )
        self.report = report

        missing = workflows.missing_requirements(self)
        if missing:
            # Raising inside @transaction.atomic undoes the report save too
            raise ValueError('این کار هنوز کامل نیست: ' + '، '.join(missing))

        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_at'])
        # Close any open return, so the history shows when it was fixed
        fixed = self.returns.filter(resubmitted_at__isnull=True).update(
            resubmitted_at=self.submitted_at,
        )
        audit_log(
            user, AuditEntry.Action.JOB_SUBMITTED, self,
            details='ارسال مجدد پس از اصلاح' if fixed else '',
        )


    def mark_reviewed(self, user):
        now = timezone.now()  # one timestamp, used for both the database and this object
        # Single UPDATE with a status condition, so two admins can't both "review" it
        updated = Job.objects.filter(pk=self.pk, status=self.Status.SUBMITTED).update(
            status=self.Status.REVIEWED,
            reviewed_by=user,
            reviewed_at=now,
            updated_at=now,
        )
        if not updated:
            raise ValueError('Only submitted jobs can be marked as reviewed.')

        # Update the in-memory object only after the database update succeeded
        self.status = self.Status.REVIEWED
        self.reviewed_by = user
        self.reviewed_at = now
        self.updated_at = now
        audit_log(user, AuditEntry.Action.JOB_REVIEWED, self)


    @transaction.atomic
    def return_for_correction(self, user, reason):
        reason = (reason or '').strip()
        if not reason:
            raise ValueError('ذکر دلیل برگشت کار الزامی است.')

        # Keep the old description, since the resubmit will overwrite it
        report = getattr(self, 'report', None)
        previous_description = report.description if report else ''

        # Conditional update: two admins can't both return the same job
        updated = Job.objects.filter(pk=self.pk, status=self.Status.SUBMITTED).update(
            status=self.Status.RETURNED,
            updated_at=timezone.now(),
        )
        if not updated:
            raise ValueError('فقط کارهای ارسال‌شده قابل برگشت هستند.')

        JobReturn.objects.create(
            job=self, reason=reason, returned_by=user,
            previous_description=previous_description,
        )
        audit_log(user, AuditEntry.Action.JOB_RETURNED, self, details=reason)
        self.status = self.Status.RETURNED


def job_photo_path(instance, filename):
    # This function name is kept on purpose: old migrations import it.
    # It now builds the folder path for every evidence file.
    return f'job_evidence/job_{instance.job_id}/{instance.category}/{filename}'


class JobEvidence(models.Model):
    class Kind(models.TextChoices):
        PHOTO = 'photo', 'عکس'
        VIDEO = 'video', 'ویدیو'

    class Category(models.TextChoices):
        # Old generic steps (still used by the current technician flow)
        BEFORE = 'before', 'قبل'
        DURING = 'during', 'حین کار'
        AFTER = 'after', 'بعد'
        # Photos that need no name
        GENERAL = 'general', 'عمومی'
        # Drop cable
        CABLE_LOCATION = 'cable_location', 'عکس دراپ'
        FAT = 'fat', 'عکس FAT'
        ENTRANCE = 'entrance', 'عکس ورودی'
        RECEIPT = 'receipt', 'عکس رسید'
        TOKAR = 'tokar', 'عکس توکار'
        # Fusion with a splitter
        SPLITTER_BEFORE = 'splitter_before', 'قبل اجرای اسپلیتر'
        SPLITTER_AFTER = 'splitter_after', 'بعد اجرای اسپلیتر'
        CASSETTE = 'cassette', 'آرایش کاست'
        # Service delivery
        MOM = 'mom', 'عکس صورت جلسه'
        PON_TEST = 'pon_test', 'عکس تست پان'
        SPEED_TEST = 'speed_test', 'عکس تست سرعت'
        # Videos
        VIDEO = 'video', 'ویدیو'

    

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='evidence')
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PHOTO)
    category = models.CharField(max_length=30, choices=Category.choices)
    file = models.FileField(upload_to=job_photo_path)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name_plural = 'job evidence'
        constraints = [
            models.CheckConstraint(
                name='evidence_kind_matches_category',
                condition=(
                    models.Q(kind='video', category='video')
                    | (models.Q(kind='photo') & ~models.Q(category='video'))
                ),
            ),
        ]

    def __str__(self):
        return f"{self.job} - {self.category}"




class WorkReport(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='report')
    description = models.TextField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.job}"




class JobMaterialUsage(models.Model):
    class Purpose(models.TextChoices):
        USED = 'used', 'استفاده‌شده'
        NEEDED = 'needed', 'مورد نیاز'

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='material_usages')
    material = models.ForeignKey(
        'inventory.Material', on_delete=models.PROTECT, related_name='usages',
    )
    # Copies taken when the row is first saved, so the job keeps its own record
    material_code = models.CharField(max_length=50, editable=False)
    material_name = models.CharField(max_length=200, editable=False)
    unit = models.CharField(max_length=30, editable=False)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.USED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['material_code']
        constraints = [
            models.UniqueConstraint(fields=['job', 'material'], name='unique_material_per_job'),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='material_quantity_positive'),
        ]

    def save(self, *args, **kwargs):
        if not self.material_code:
            self.material_code = self.material.code
            self.material_name = self.material.name
            self.unit = self.material.unit
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.material_id and self.quantity is not None:
            quantity = Decimal(str(self.quantity))
            if (self.material.unit == self.material.UNIT_PIECE
                    and quantity != quantity.to_integral_value()):
                raise ValidationError({'quantity': 'برای این ماده فقط عدد صحیح مجاز است.'})

    def __str__(self):
        return f"{self.material_code} × {self.quantity}"





class JobReturn(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='returns')
    reason = models.TextField()
    previous_description = models.TextField(blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='job_returns_made',
    )
    returned_at = models.DateTimeField(auto_now_add=True)
    resubmitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-returned_at']

    def __str__(self):
        return f"Return of job #{self.job_id} at {self.returned_at}"