from django.db import models
from django.utils import timezone
from datetime import timedelta
from core.auth_helper import AuthHelper

auth_helper = AuthHelper()  # 初始化 AuthHelper

class UserToken(models.Model):
    user_id = models.CharField(max_length=255, unique=True)
    user_email = models.EmailField(unique=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def refresh_token_if_needed(self):
        if self.is_expired():
            auth_app = auth_helper.get_msal_app()
            result = auth_app.acquire_token_by_refresh_token(
                self.refresh_token,
                scopes=auth_helper.settings['scopes'],
            )
            if result:
                self.access_token = result['access_token']
                self.refresh_token = result.get('refresh_token', self.refresh_token)
                self.expires_at = timezone.now() + timedelta(seconds=result['expires_in'])
                self.created_at = timezone.now()
                self.save()
            else:
                print("Failed to refresh token. Please sign in again.")

    def get_token(self):
        """
        Returns a valid access token, refreshing it if necessary.
        """
        if self.is_expired():
            self.refresh_token_if_needed()
        return self.access_token
