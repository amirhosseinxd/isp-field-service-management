from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.core.validators import MinValueValidator

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

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def photo_count(self, category):
        return self.evidence.filter(
            kind=JobEvidence.Kind.PHOTO, category=category,
        ).count()

    def missing_requirements(self):
        """Everything still needed before this job can be submitted (old generic rules)."""
        missing = []
        if not self.has_location:
            missing.append('موقعیت مکانی')

        for stage in JobEvidence.LEGACY_STAGES:
            if self.photo_count(stage) < 1:
                missing.append(f'عکس {JobEvidence.Category(stage).label}')

        return missing

    def next_step(self):
        """First incomplete step, in the technician's required order."""
        if not self.has_location:
            return 'location'
        for stage in (JobEvidence.Category.BEFORE, JobEvidence.Category.DURING, JobEvidence.Category.AFTER):
            if self.photo_count(stage) < 1:
                return stage
        if not hasattr(self, 'report'):
            return 'report'
        return 'done'

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



    def mark_reviewed(self, user):
        now = timezone.now()  # one timestamp, used for both the database and this object
        # Single UPDATE with a status condition, so two admins can't both "review" it
        updated = Job.objects.filter(pk=self.pk, status=self.Status.SUBMITTED).update(
            status=self.Status.REVIEWED,
            reviewed_by=user,
            reviewed_at=now,
        )
        if not updated:
            raise ValueError('Only submitted jobs can be marked as reviewed.')

        # Update the in-memory object only after the database update succeeded
        self.status = self.Status.REVIEWED
        self.reviewed_by = user
        self.reviewed_at = now


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

    # The three stages the current (old) technician flow uses
    LEGACY_STAGES = (Category.BEFORE, Category.DURING, Category.AFTER)

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