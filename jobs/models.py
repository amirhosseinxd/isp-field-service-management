from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class Job(models.Model):
    class JobType(models.TextChoices):
        INSTALLATION = 'installation', 'نصب'
        REPAIR = 'repair', 'تعمیر'

    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'ارجاع شده'
        IN_PROGRESS = 'in_progress', 'در حال انجام'
        SUBMITTED = 'submitted', 'ارسال شده'
        REVIEWED = 'reviewed', 'بررسی شده'

    job_type = models.CharField(max_length=20, choices=JobType.choices)
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

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job #{self.pk} - {self.get_job_type_display()}"

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def photo_count(self, stage):
        return self.photos.filter(stage=stage).count()

    def missing_requirements(self):
        """Everything still needed before this job can be submitted."""
        missing = []
        if not self.has_location:
            missing.append('موقعیت مکانی')

        for stage, label in JobPhoto.Stage.choices:
            if self.photo_count(stage) < 1:
                missing.append(f'عکس {label}')
        return missing

    def next_step(self):
        """First incomplete step, in the technician's required order."""
        if not self.has_location:
            return 'location'
        for stage in (JobPhoto.Stage.BEFORE, JobPhoto.Stage.DURING, JobPhoto.Stage.AFTER):
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


def job_photo_path(instance, filename):
    return f'job_photos/job_{instance.job_id}/{instance.stage}/{filename}'


class JobPhoto(models.Model):
    class Stage(models.TextChoices):
        BEFORE = 'before', 'قبل'
        DURING = 'during', 'حین کار'
        AFTER = 'after', 'بعد'

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=job_photo_path)
    stage = models.CharField(max_length=10, choices=Stage.choices)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"{self.job} - {self.stage}"


class WorkReport(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='report')
    description = models.TextField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.job}"