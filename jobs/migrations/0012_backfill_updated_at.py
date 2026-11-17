from django.db import migrations
from django.db.models import Max


def backfill(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    for job in Job.objects.annotate(last_evidence=Max('evidence__uploaded_at')):
        candidates = [
            t for t in (job.created_at, job.submitted_at, job.reviewed_at, job.last_evidence)
            if t
        ]
        Job.objects.filter(pk=job.pk).update(updated_at=max(candidates))


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0011_job_updated_at'),
    ]


    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]