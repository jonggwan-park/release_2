# Generated by Django 4.2 on 2025-03-11 05:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0009_alter_user_preferred_game_alter_user_preferred_genre_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='nickname',
            field=models.CharField(max_length=50, unique=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='steam_id',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
    ]
