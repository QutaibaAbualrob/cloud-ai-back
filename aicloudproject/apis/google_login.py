"""
Google social login + Gmail OAuth for CloudAI.

- POST /api/auth/google/         — verify Google ID token (JWT), return DRF auth token
- GET  /api/auth/google/oauth-url/ — return Google OAuth 2.0 consent URL for Gmail access
- GET  /api/auth/google/callback/  — exchange auth code for tokens, create EmailAccount
"""

import logging
import secrets
import urllib.parse

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import EmailAccount

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def google_login(request):
    """
    POST /api/auth/google/

    Accepts a Google ID token (JWT credential) from the frontend,
    verifies it server-side, and returns a DRF auth token.

    Request body:
        {"access_token": "<google-id-token-jwt>"}

    Response (200):
        {"key": "<drf-auth-token>", "user": {"id": ..., "username": ..., "email": ...}}

    Response (400):
        {"error": "Token verification failed"}
    """
    token_jwt = request.data.get("access_token")
    if not token_jwt:
        return Response(
            {"error": "access_token is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify the JWT using Google's public keys
    user_info = _verify_google_token(token_jwt)
    if user_info is None:
        return Response(
            {"error": "Token verification failed"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = user_info.get("email", "")
    google_sub = user_info.get("sub", "")
    name = user_info.get("name", "")
    given_name = user_info.get("given_name", "")

    if not email:
        return Response(
            {"error": "Email not provided by Google"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find or create the user
    user, created = User.objects.get_or_create(
        username=email.split("@")[0],
        defaults={
            "email": email,
            "first_name": given_name or name,
        },
    )

    if created:
        logger.info(f"Created new user via Google login: {email}")

    # Ensure email is set (in case user existed but email was different)
    if not user.email:
        user.email = email
        user.save(update_fields=["email"])

    # Generate or retrieve DRF auth token
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        "key": token.key,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
        },
    })


def _verify_google_token(token_jwt):
    """
    Verify a Google ID token JWT using google.auth library.

    Returns:
        dict with user info (sub, email, name, picture) or None if verification fails.
    """
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests

        request = requests.Request()
        client_id = settings.GOOGLE_OAUTH2_CLIENT_ID

        if not client_id:
            logger.error("GOOGLE_OAUTH2_CLIENT_ID is not configured")
            return None

        # verify_oauth2_token checks:
        # - The JWT signature against Google's public keys
        # - The 'aud' claim matches our client ID
        # - The 'iss' claim is accounts.google.com
        # - The token hasn't expired
        info = id_token.verify_oauth2_token(token_jwt, request, client_id, clock_skew_in_seconds=60)

        # Optionally also check the issuer
        if info.get("iss") not in [
            "accounts.google.com",
            "https://accounts.google.com",
        ]:
            logger.warning(f"Invalid token issuer: {info.get('iss')}")
            return None

        return info

    except ValueError as e:
        # Token is invalid or expired
        logger.warning(f"Google token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying Google token: {e}")
        return None


# ── Gmail OAuth 2.0 (Authorization Code Flow) ────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def google_oauth_url(request):
    """
    GET /api/auth/google/oauth-url/

    Returns a Google OAuth 2.0 consent URL that the frontend can
    redirect the user to. After the user grants permission, Google
    redirects to our callback endpoint with an authorization code.

    Query params:
        email  (optional) — pre-fill the EmailAccount email_address

    Returns (200):
        {"url": "https://accounts.google.com/o/oauth2/v2/auth?..."}
    """
    client_id = settings.GOOGLE_OAUTH2_CLIENT_ID
    redirect_uri = settings.GOOGLE_OAUTH2_REDIRECT_URI
    scopes = settings.GMAIL_SCOPES

    if not client_id:
        return Response(
            {"error": "GOOGLE_OAUTH2_CLIENT_ID is not configured"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Build a stateless CSRF token: "random:user_id:prefilled_email"
    random_part = secrets.token_urlsafe(32)
    user_id = str(request.user.id)
    prefilled_email = request.query_params.get("email", "")
    state_raw = f"{random_part}:{user_id}:{prefilled_email}"
    # Base64-encode to keep it URL-safe (state is opaque to Google)
    state = urllib.parse.quote(state_raw)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",       # get refresh_token
        "prompt": "consent",            # force consent screen to always get refresh_token
        "state": state,
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    return Response({"url": auth_url})


@api_view(["GET"])
@permission_classes([AllowAny])
def google_oauth_callback(request):
    """
    GET /api/auth/google/callback/

    Google redirects here after the user grants/denies Gmail access.
    Exchanges the authorization code for access + refresh tokens,
    creates an EmailAccount with the tokens, and redirects to the
    frontend Accounts page.

    In development, the frontend is at http://localhost:5173.
    """
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")

    frontend_url = settings.GOOGLE_OAUTH_FRONTEND_REDIRECT or "http://localhost:5173/accounts"

    # Decode the stateless state token: "random:user_id:prefilled_email"
    user_id = None
    prefilled_email = ""
    if state:
        try:
            state_raw = urllib.parse.unquote(state)
            parts = state_raw.split(":", 2)
            # parts[0] = random (unused, just for CSRF uniqueness)
            if len(parts) >= 2:
                user_id = int(parts[1])
            if len(parts) >= 3:
                prefilled_email = parts[2]
        except (ValueError, IndexError):
            logger.warning("Google OAuth callback: invalid state format")
            return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=invalid_state")

    if not user_id:
        logger.warning("Google OAuth callback: no user_id in state")
        return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=no_user")

    if error:
        logger.warning(f"Google OAuth callback: user denied access ({error})")
        return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason={error}")

    if not code:
        return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=no_code")

    client_id = settings.GOOGLE_OAUTH2_CLIENT_ID
    client_secret = settings.GOOGLE_OAUTH2_CLIENT_SECRET
    redirect_uri = settings.GOOGLE_OAUTH2_REDIRECT_URI

    if not client_id or not client_secret:
        logger.error("Google OAuth credentials not configured")
        return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=not_configured")

    try:
        # Exchange the authorization code for tokens
        creds = Credentials(
            token=None,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )

        # Perform the code exchange (fetch_token does the POST to Google)
        creds_response = _exchange_code_for_tokens(code, client_id, client_secret, redirect_uri)
        if not creds_response:
            return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=token_exchange_failed")

        access_token = creds_response.get("access_token")
        refresh_token = creds_response.get("refresh_token")
        expires_in = creds_response.get("expires_in", 3600)

        if not access_token:
            return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=no_access_token")

        # Get the user's email from Gmail API using the new access token
        email_address = _get_gmail_address(access_token)
        if not email_address:
            # Fallback: use the pre-filled email from the state token
            email_address = prefilled_email
        if not email_address:
            return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=cannot_get_email")

        # Find the user who initiated the OAuth (from the stateless state token)
        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=user_not_found")

        # Calculate token expiry
        from datetime import datetime, timezone as dt_timezone
        from django.utils import timezone
        token_expiry = timezone.now() + timezone.timedelta(seconds=expires_in)

        # Create or update the EmailAccount
        account, created = EmailAccount.objects.update_or_create(
            user=user,
            email_address=email_address,
            provider="gmail",
            defaults={
                "access_token": access_token,
                "refresh_token": refresh_token or "",
                "token_expiry": token_expiry,
                "is_active": True,
            },
        )

        logger.info(
            "Gmail OAuth: %s EmailAccount '%s' for user %s (refresh_token=%s)",
            "created" if created else "updated",
            email_address,
            user.username,
            "present" if refresh_token else "missing",
        )

        return HttpResponseRedirect(f"{frontend_url}?oauth=success&email={urllib.parse.quote(email_address)}")

    except Exception as e:
        logger.error("Google OAuth callback error: %s", e, exc_info=True)
        return HttpResponseRedirect(f"{frontend_url}?oauth=error&reason=server_error")


def _exchange_code_for_tokens(code, client_id, client_secret, redirect_uri):
    """Exchange an OAuth authorization code for access + refresh tokens."""
    import requests as http_requests

    try:
        resp = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Token exchange failed: %s", e)
        return None


def _get_gmail_address(access_token):
    """Use the Gmail API to get the authenticated user's email address."""
    try:
        creds = Credentials(token=access_token)
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress")
    except Exception as e:
        logger.error("Failed to get Gmail profile: %s", e)
        return None
