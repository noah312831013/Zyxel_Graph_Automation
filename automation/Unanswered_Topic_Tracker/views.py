from django.shortcuts import render
from django import forms
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views import View
from core.teams_client import TeamsClient
from core.views import initialize_context


class ChatIDForm(forms.Form):
    chat_id = forms.ChoiceField(label="選擇你的聊天室")

    def __init__(self, *args, **kwargs):
        chat_ids = kwargs.pop('chat_ids', [])
        super().__init__(*args, **kwargs)
        self.fields['chat_id'].choices = [(cid['id'], cid['topic']) for cid in chat_ids]

class UnansweredTopicView(View):
    template_name = "unanswered_topic_form.html"
    def get(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        teams_client = TeamsClient(context['user']['id'])
        chat_ids = teams_client.get_chats()
        # chat_ids is a list of dicts with keys like 'id', 'topic', etc.
        form = ChatIDForm(chat_ids=chat_ids)
        context['form'] = form
        return render(request, self.template_name, context)

    def post(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        teams_client = TeamsClient(user['id'])
        chat_ids = teams_client.get_chats()
        form = ChatIDForm(request.POST, chat_ids=chat_ids)
        if form.is_valid():
            chat_id = form.cleaned_data['chat_id']
            user_id = user['id']
            # schedule_unanswered_topic_task.delay(chat_id, user_id)
            return JsonResponse({'chat_id': chat_id})
        context['form'] = form
        return render(request, self.template_name, context)