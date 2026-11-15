import django.db.models.deletion
from django.db import migrations, models

import customers.models

CITIES = [
    'سمنان', 'شاهرود', 'دامغان', 'گرمسار', 'مهدی‌شهر', 'ایوانکی', 'شهمیرزاد', 'سرخه',
    'بسطام', 'آرادان', 'مجن', 'کلاته خیج', 'درجزین', 'دیباج', 'کلاته', 'میامی',
    'رودیان', 'امیریه', 'بیارجمند', 'کهن‌آباد', 'رضوان',
]


def load_cities(apps, schema_editor):
    City = apps.get_model('customers', 'City')
    for name in CITIES:
        City.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0002_customer_status_label_alter_customer_subscription_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='City',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
            ],
            options={'ordering': ['name'], 'verbose_name_plural': 'cities'},
        ),
        migrations.RunPython(load_cities, migrations.RunPython.noop),
        migrations.RemoveField(model_name='customer', name='city'),
        migrations.RemoveField(model_name='customer', name='center'),
        migrations.AddField(
            model_name='customer',
            name='city',
            field=models.ForeignKey(
                default=1, on_delete=django.db.models.deletion.PROTECT,
                related_name='customers', to='customers.city',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='customer',
            name='center_number',
            field=models.CharField(
                default='00', max_length=2,
                validators=[customers.models.center_number_validator],
            ),
            preserve_default=False,
        ),
    ]