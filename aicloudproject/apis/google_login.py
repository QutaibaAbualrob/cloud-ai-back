"""
Google social login views for InboxIQ.

Uses dj-rest-auth + allauth to handle Google OAuth 2.0 sign-in and sign-up.
The frontend obtains a Google ID token via Google Identity Services,
then sends it to the login endpoint to receive a Django auth token.
"""

from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client


class GoogleLogin(SocialLoginView):
    """
    POST /api/auth/google/

    Accepts an access token obtained from Google Identity Services
    and returns a Django Rest Framework auth token.

    Request body:
        {"access_token": "<google-id-token>"}

    Response (200):
        {"key": "<drf-auth-token>", "user": {...}}
    """
    adapter_class = GoogleOAuth2Adapter
    callback_url = "http://localhost:5173"
    client_class = OAuth2Client
