from django.db import migrations

# Name changes only. The codes, units and everything else stay the same.
RENAMES = {
    'M001': 'دراپ 2کر',   # was: دراپ
    'M004': 'مینی',       # was: دراپ 8 کر
    'M016': 'پچکورد',     # was: پچگورد
}


def convert_repair_jobs(apps, schema_editor):
    # Installation allows every workflow that repair allowed, so no job is lost
    Job = apps.get_model('jobs', 'Job')
    Job.objects.filter(job_type='repair').update(job_type='installation')


def rename_materials(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    Usage = apps.get_model('jobs', 'JobMaterialUsage')
    for code, name in RENAMES.items():
        Material.objects.filter(code=code).update(name=name)
        # Past jobs keep their own copy of the name, so those copies are renamed too
        Usage.objects.filter(material_code=code).update(material_name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0012_backfill_updated_at') , ('inventory', '0003_real_materials'), 
    ]

    operations = [
        migrations.RunPython(convert_repair_jobs, migrations.RunPython.noop),
        migrations.RunPython(rename_materials, migrations.RunPython.noop),
    ]