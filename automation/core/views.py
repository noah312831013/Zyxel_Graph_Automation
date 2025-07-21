from django.shortcuts import render
from django.http import HttpResponseRedirect,HttpResponse
from django.urls import reverse
from django.utils import timezone
from core.models import UserToken
from core.auth_helper import AuthHelper
from datetime import timedelta
from automation.celery import debug_task
import requests
import base64
def initialize_context(request):
    context = {}

    # Check for any errors in the session
    error = request.session.pop('flash_error', None)

    if error is not None:
        context['errors'] = []
        context['errors'].append(error)

    # Check for user in the session
    context['user'] = request.session.get('user', {'is_authenticated': False})
    return context

def home(request):
    context = initialize_context(request)
    user = request.session.get('user')
    
    if user and user.get('id'):
        user_token = UserToken.objects.filter(user_id=user.get('id')).first()
        if user_token:
            user_token.refresh_token_if_needed()
    
    return render(request, 'home.html', context)

auth_helper = AuthHelper()  # 初始化 AuthHelper

def sign_in(request):
    flow = auth_helper.get_sign_in_flow()
    request.session['auth_flow'] = flow
    return HttpResponseRedirect(flow['auth_uri'])

def callback(request):
    result = auth_helper.get_token_from_code(request)
    # 檢查 response 是否包含 access_token
    if not result or 'access_token' not in result:
        print("Token response error:", result)  # 建議 log 起來
        return HttpResponse(
            f"Token acquisition failed: {result.get('error_description', result)}",
            status=400
        )
    token_data = {
        'access_token': result['access_token'],
        'refresh_token': result['refresh_token'],
        'expires_in': result['expires_in']
    }

    headers = {
        'Authorization': f'Bearer {token_data['access_token']}',
        'Accept': 'application/json'
    }

    # Get user basic info
    user_info = requests.get(
        'https://graph.microsoft.com/v1.0/me',
        headers=headers,
        params={
            '$select': 'displayName,mail,mailboxSettings,userPrincipalName,id'
        }
    ).json()

    # Get user photo (profile picture)
    photo_response = requests.get(
        'https://graph.microsoft.com/v1.0/me/photo/$value',
        headers=headers
    )
    if photo_response.status_code == 200:
        user_info['avatar'] = base64.b64encode(photo_response.content).decode('utf-8')
    else:
        user_info['avatar'] = None
    
    user_id = user_info.get('id')
    user_email = user_info.get('mail') or user_info.get('userPrincipalName')

    expires_at = timezone.now() + timedelta(seconds=token_data['expires_in'])

    UserToken.objects.update_or_create(
        user_id=user_id,
        defaults={
            'user_email': user_email,
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'expires_at': expires_at,
        }
    )

    auth_helper.store_user(request, user_info)
    return HttpResponseRedirect(reverse('home'))

def sign_out(request):
    auth_helper.remove_user_and_token(request)
    return HttpResponseRedirect(reverse('home'))