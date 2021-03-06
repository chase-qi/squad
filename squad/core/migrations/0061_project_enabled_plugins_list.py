# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-18 19:02
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0060_test_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='enabled_plugins_list',
            field=models.TextField(default='', help_text='One per line. Non-existing plugins are ignored.', validators=[django.core.validators.RegexValidator(regex='^$|^[a-zA-Z0-9][a-zA-Z0-9_.-]*(\\s+[a-zA-Z0-9][a-zA-Z0-9_.-]*)*$')]),
        ),
    ]
