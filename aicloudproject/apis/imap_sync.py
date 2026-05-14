"""
IMAP email synchronization module.

Fallback connector for providers that don't support OAuth.
Uses Python's built-in imaplib with SSL.
"""

import email
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from email.header import decode_header
from email.policy import default

import imaplib
from django.utils.timezone import make_aware

from .models import EmailAccount, Email

logger = logging.getLogger(__name__)


def decode_mime_header(value):
    """Decode an RFC 2047 encoded header value to a plain string."""
    if value is None:
        return ''
    parts = decode_header(value)
    result = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                text = text.decode(charset or 'utf-8', errors='replace')
            except (LookupError, TypeError):
                text = text.decode('utf-8', errors='replace')
        result.append(text)
    return ' '.join(result)


def extract_text_from_message(msg):
    """
    Extract plain text and HTML body from an email.message.Message.

    Walks multipart MIME structure recursively.
    Returns: (body_text, body_html)
    """
    body_text = ''
    body_html = ''

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))

            # Skip attachments
            if 'attachment' in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or 'utf-8'
                text = payload.decode(charset, errors='replace')
            except Exception:
                continue

            if content_type == 'text/plain':
                body_text += text
            elif content_type == 'text/html':
                body_html += text
    else:
        # Single-part message
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                text = payload.decode(charset, errors='replace')
                if content_type == 'text/plain':
                    body_text = text
                elif content_type == 'text/html':
                    body_html = text
        except Exception:
            pass

    return body_text, body_html


def sync_imap_account(email_account: EmailAccount, max_emails: int = 100) -> int:
    """
    Sync emails from an IMAP account.

    Args:
        email_account: EmailAccount with provider='imap' and valid credentials.
        max_emails: Maximum number of new emails to fetch.

    Returns:
        Number of new emails created.
    """
    if email_account.imap_use_ssl:
        MailboxClass = imaplib.IMAP4_SSL
    else:
        MailboxClass = imaplib.IMAP4

    try:
        mailbox = MailboxClass(email_account.imap_host, email_account.imap_port)
        mailbox.login(email_account.imap_username, email_account.imap_password)
        mailbox.select('INBOX')
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP connection failed for {email_account.email_address}: {e}")
        return 0

    # Get existing external IDs to skip duplicates
    existing_ids = set(
        Email.objects.filter(
            email_account=email_account
        ).values_list('external_id', flat=True)
    )

    # Search for recent messages (last 30 days)
    status, message_ids = mailbox.search(None, '(UNSEEN)')
    if status != 'OK':
        mailbox.logout()
        return 0

    id_list = message_ids[0].split()
    created_count = 0

    # Process newest first
    for msg_id_str in reversed(id_list):
        if created_count >= max_emails:
            break

        status, msg_data = mailbox.fetch(msg_id_str, '(RFC822)')
        if status != 'OK':
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email, policy=default)

        # Extract headers
        subject = decode_mime_header(msg.get('Subject', ''))
        from_header = decode_mime_header(msg.get('From', ''))
        to_header = decode_mime_header(msg.get('To', ''))
        message_id = msg.get('Message-ID', '').strip('<>')

        # Parse sender
        sender_name = ''
        sender_email_addr = ''
        if '<' in from_header:
            parts = from_header.rsplit('<', 1)
            sender_name = parts[0].strip().strip('"')
            sender_email_addr = parts[1].rstrip('>').strip()
        else:
            sender_email_addr = from_header.strip()

        # Parse date
        date_header = msg.get('Date', '')
        received_at = None
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed and parsed.tzinfo is None:
                parsed = make_aware(parsed, timezone.utc)
            received_at = parsed
        except (ValueError, TypeError):
            received_at = datetime.now(timezone.utc)

        # Skip if already exists (use Message-ID or composite key)
        if message_id and message_id in existing_ids:
            continue

        body_text, body_html = extract_text_from_message(msg)

        # Create snippet (first 300 chars of text)
        snippet = body_text[:300] if body_text else ''

        Email.objects.create(
            user=email_account.user,
            email_account=email_account,
            external_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
            sender_name=sender_name,
            sender_email=sender_email_addr,
            recipient_email=to_header,
            subject=subject,
            received_at=received_at,
            body_text=body_text,
            body_html=body_html,
            snippet=snippet,
        )

        if message_id:
            existing_ids.add(
                message_id.decode() if isinstance(message_id, bytes) else message_id
            )
        created_count += 1

    mailbox.logout()

    email_account.last_synced_at = datetime.now(timezone.utc)
    email_account.save(update_fields=['last_synced_at'])

    logger.info(f"IMAP synced {created_count} emails for {email_account.email_address}")
    return created_count
