from django.contrib import admin
from .models import UserToken
from django_celery_beat.models import PeriodicTask, IntervalSchedule
# Register your models here.
admin.site.register(UserToken)

admin.site.register(PeriodicTask)
admin.site.register(IntervalSchedule)