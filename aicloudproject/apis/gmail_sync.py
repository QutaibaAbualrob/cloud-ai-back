"""
Gmail API synchronization module.

Uses google-api-python-client to fetch emails via Gmail API.
Supports incremental sync via historyId to minimize API calls.
"""

import base64
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from django.utils.timezone import make_aware

from django.conf import settings

from .models import EmailAccount, Email

logger = logging.getLogger(__name__)


def get_gmail_service(email_account: EmailAccount):
    """
    Build an authenticated Gmail API service for the given EmailAccount.

    Args:
        email_account: EmailAccount instance with valid OAuth tokens.

    Returns:
        googleapiclient.discovery.Resource or None if tokens are invalid.
    """
    creds = Credentials(
        token=email_account.access_token,
        refresh_token=email_account.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_OAUTH2_CLIENT_ID or None,
        client_secret=settings.GOOGLE_OAUTH2_CLIENT_SECRET or None,
        scopes=['https://www.googleapis.com/auth/gmail.readonly'],
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        email_account.access_token = creds.token
        email_account.token_expiry = creds.expiry
        email_account.save(update_fields=['access_token', 'token_expiry'])

    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Gmail service for {email_account.email_address}: {e}")
        return None


def list_messages(service, query='', max_results=100, page_token=None):
    """
    List message IDs from Gmail.

    Args:
        service: Gmail API service instance.
        query: Gmail search query (e.g., 'is:unread', 'newer_than:1d').
        max_results: Maximum messages per page.
        page_token: Token for pagination.

    Returns:
        Dict with 'messages' (list of {id, threadId}) and optional 'nextPageToken'.
    """
    try:
        params = {'userId': 'me', 'maxResults': max_results, 'q': query}
        if page_token:
            params['pageToken'] = page_token
        response = service.users().messages().list(**params).execute()
        return response
    except HttpError as e:
        logger.error(f"Gmail API list error: {e}")
        return {'messages': []}


def get_message(service, message_id):
    """
    Fetch a full message by ID, including parsed headers and body.

    Returns:
        Dict with 'id', 'threadId', 'payload' containing headers and body data.
    """
    try:
        message = service.users().messages().get(
            userId='me', id=message_id, format='full'
        ).execute()
        return message
    except HttpError as e:
        logger.error(f"Gmail API get message error for {message_id}: {e}")
        return None


def extract_headers(message):
    """
    Extract standard email headers from a Gmail API message payload.

    Args:
        message: Full Gmail message dict.

    Returns:
        Dict with 'subject', 'sender_name', 'sender_email', 'recipient_email',
        'date', 'message_id', 'thread_id'.
    """
    headers = {}
    payload = message.get('payload', {})
    for header in payload.get('headers', []):
        name = header.get('name', '').lower()
        value = header.get('value', '')
        if name == 'subject':
            headers['subject'] = value
        elif name == 'from':
            headers['from_raw'] = value
            # Parse "Name <email>" format
            if '<' in value:
                parts = value.rsplit('<', 1)
                headers['sender_name'] = parts[0].strip().strip('"')
                headers['sender_email'] = parts[1].rstrip('>').strip()
            else:
                headers['sender_name'] = ''
                headers['sender_email'] = value.strip()
        elif name == 'to':
            headers['to_raw'] = value
            # Take first recipient for simplicity
            recipient = value.split(',')[0].strip()
            if '<' in recipient:
                headers['recipient_email'] = recipient.split('<')[1].rstrip('>').strip()
            else:
                headers['recipient_email'] = recipient
        elif name == 'date':
            headers['date'] = value
        elif name == 'message-id':
            headers['message_id'] = value

    headers['thread_id'] = message.get('threadId', '')
    return headers


def extract_body(message):
    """
    Extract plain text and HTML body from a Gmail message.

    Handles multipart MIME messages recursively.
    Returns: (body_text, body_html, snippet)
    """
    body_text = ''
    body_html = ''
    snippet = message.get('snippet', '')

    def _walk_parts(part):
        nonlocal body_text, body_html
        mime_type = part.get('mimeType', '')
        body = part.get('body', {})

        if mime_type == 'text/plain':
            data = body.get('data', '')
            if data:
                body_text += base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        elif mime_type == 'text/html':
            data = body.get('data', '')
            if data:
                body_html += base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        for sub_part in part.get('parts', []):
            _walk_parts(sub_part)

    payload = message.get('payload', {})
    _walk_parts(payload)
    return body_text, body_html, snippet


def parse_date(date_string):
    """Parse an RFC 2822 date string into a timezone-aware datetime."""
    if not date_string:
        return None
    try:
        parsed = parsedate_to_datetime(date_string)
        if parsed.tzinfo is None:
            parsed = make_aware(parsed, timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def sync_gmail_account(email_account: EmailAccount, max_emails: int = 100) -> int:
    """
    Sync emails from a single Gmail account.

    Args:
        email_account: EmailAccount with provider='gmail' and valid tokens.
        max_emails: Maximum number of messages to fetch in this sync cycle.

    Returns:
        Number of new emails created.
    """
    service = get_gmail_service(email_account)
    if not service:
        return 0

    # Get existing external IDs to skip duplicates
    existing_ids = set(
        Email.objects.filter(
            email_account=email_account
        ).values_list('external_id', flat=True)
    )

    created_count = 0
    page_token = None

    while created_count < max_emails:
        response = list_messages(service, query='in:inbox', max_results=50, page_token=page_token)
        messages = response.get('messages', [])

        if not messages:
            break

        for msg_summary in messages:
            if created_count >= max_emails:
                break

            msg_id = msg_summary['id']
            if msg_id in existing_ids:
                continue

            full_msg = get_message(service, msg_id)
            if not full_msg:
                continue

            headers = extract_headers(full_msg)
            body_text, body_html, snippet = extract_body(full_msg)
            received_at = parse_date(headers.get('date'))

            Email.objects.create(
                user=email_account.user,
                email_account=email_account,
                external_id=msg_id,
                thread_id=full_msg.get('threadId', ''),
                sender_name=headers.get('sender_name', ''),
                sender_email=headers.get('sender_email', ''),
                recipient_email=headers.get('recipient_email', ''),
                subject=headers.get('subject', ''),
                received_at=received_at,
                body_text=body_text,
                body_html=body_html,
                snippet=snippet,
            )

            existing_ids.add(msg_id)
            created_count += 1

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    # Update last synced timestamp
    email_account.last_synced_at = datetime.now(timezone.utc)
    email_account.save(update_fields=['last_synced_at'])

    logger.info(f"Synced {created_count} new emails for {email_account.email_address}")
    return created_count
