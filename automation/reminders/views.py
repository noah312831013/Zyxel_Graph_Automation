from django.shortcuts import render
from core.views import initialize_context
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from core.models import UserToken
from .sharepoint_client import GraphSharePointClient
import time
from .models import TaskNotification

# Create your views here.

def sharepoint_reminder_dashboard(request):
    context = initialize_context(request)
    user = context['user']
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    return render(request, "sharepoint_reminder_dashboard.html", context)

def add_schedule_task(request):
    """
    Starts the scan routine and polling tasks
    """
    # Initialize GraphSharePointClient
    context = initialize_context(request)
    SP = GraphSharePointClient(context['user']['id'])
    # write task to disk
    SP.create_notify_items(int(request.POST.get('routine_interval')))
    return JsonResponse({"message": "Tasks started successfully"})

def get_tracking_items(request):
    """
    Returns the list of tracking items for real-time updates.
    """
    
    items = TaskNotification.objects.filter(host_id=request.session['user']['id']).values(
        "sheet_name", "row", "task", "owner_name", "reason", "status"
    )
    return JsonResponse(list(items), safe=False)