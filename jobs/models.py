from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

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
    created_at = models.DateTimeField(auto_now_add=True)

    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='jobs_reviewed',
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

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
        """Everything still needed before this job can be submitted."""
        missing = []
        if not self.has_location:
            missing.append('موقعیت مکانی')

        for stage, label in JobEvidence.Category.choices:
            if self.photo_count(stage) < 1:
                missing.append(f'عکس {label}')
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
        if self.assigned_operator_id != user.id:
            raise PermissionError('Only the assigned operator can submit this job.')
        if self.status in (self.Status.SUBMITTED, self.Status.REVIEWED):
            raise ValueError('This job was already submitted.')
        missing = self.missing_requirements()
        if missing:
            raise ValueError('Missing: ' + ', '.join(missing))
        if not description.strip():
            raise ValueError('A description is required.')

        WorkReport.objects.create(job=self, description=description.strip(), submitted_by=user)
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
        BEFORE = 'before', 'قبل'
        DURING = 'during', 'حین کار'
        AFTER = 'after', 'بعد'

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='evidence')
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PHOTO)
    category = models.CharField(max_length=30, choices=Category.choices)
    file = models.FileField(upload_to=job_photo_path)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name_plural = 'job evidence'

    def __str__(self):
        return f"{self.job} - {self.category}"




class WorkReport(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='report')
    description = models.TextField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.job}"