"""
Google social login for InboxIQ.

Verifies Google ID tokens (JWT) obtained from Google Identity Services
on the client side, then creates/retrieves the user and returns a
Django Rest Framework auth token.

Uses google-auth library to verify the token signature with Google's
public keys — no separate API call to Google needed.
"""

import logging
from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

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
        info = id_token.verify_oauth2_token(token_jwt, request, client_id)

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
