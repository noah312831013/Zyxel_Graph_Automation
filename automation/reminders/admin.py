from django.contrib import admin
from .models import TaskNotification, TaskManager
# Register your models here.
admin.site.register(TaskNotification)
admin.site.register(TaskManager)
