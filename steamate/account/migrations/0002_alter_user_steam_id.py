# Generated by Django 4.2 on 2025-03-07 01:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='steam_id',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
