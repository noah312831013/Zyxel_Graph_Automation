# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import yaml
import msal

class AuthHelper:
    def __init__(self, settings_path='./core/oauth_settings.yml'):
        # Load settings from the YAML file
        with open(settings_path, 'r', encoding='utf8') as stream:
            self.settings = yaml.load(stream, yaml.SafeLoader)

    def load_cache(self, request):
        # Check for a token cache in the session
        cache = msal.SerializableTokenCache()
        if request.session.get('token_cache'):
            cache.deserialize(request.session['token_cache'])
        return cache

    def save_cache(self, request, cache):
        # If cache has changed, persist back to session
        if cache.has_state_changed:
            request.session['token_cache'] = cache.serialize()

    def get_msal_app(self, cache=None):
        # Initialize the MSAL confidential client
        return msal.ConfidentialClientApplication(
            self.settings['app_id'],
            authority=self.settings['authority'],
            client_credential=self.settings['app_secret'],
            token_cache=cache
        )

    def get_sign_in_flow(self):
        auth_app = self.get_msal_app()
        return auth_app.initiate_auth_code_flow(
            self.settings['scopes'],
            redirect_uri=self.settings['redirect']
        )

    def get_token_from_code(self, request):
        cache = self.load_cache(request)
        auth_app = self.get_msal_app(cache)

        # Get the flow saved in session
        flow = request.session.pop('auth_flow', {})
        result = auth_app.acquire_token_by_auth_code_flow(flow, request.GET)
        self.save_cache(request, cache)
        return result

    def store_user(self, request, user):
        time_zone = user['mailboxSettings'].get('timeZone', 'UTC')
        request.session['user'] = {
            'is_authenticated': True,
            'id': user['id'],
            'name': user['displayName'],
            'email': user.get('mail', user['userPrincipalName']),
            'timeZone': time_zone,
            'avatar': user.get('avatar'),
        }

    def get_token(self, request):
        cache = self.load_cache(request)
        auth_app = self.get_msal_app(cache)

        accounts = auth_app.get_accounts()
        if accounts:
            result = auth_app.acquire_token_silent(
                self.settings['scopes'],
                account=accounts[0]
            )
            self.save_cache(request, cache)
            return result['access_token'] if result else None

    def remove_user_and_token(self, request):
        request.session.pop('token_cache', None)
        request.session.pop('user', None)
