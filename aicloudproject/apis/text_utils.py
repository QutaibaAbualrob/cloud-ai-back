"""
Text preprocessing utilities for email NLP pipeline.

Cleans email bodies, strips signatures and quoted replies,
and prepares normalized text for LLM API input.
"""

import re
from html import unescape


def strip_html(html_text: str) -> str:
    """
    Remove HTML tags and decode entities from an HTML email body.
    Returns plain text suitable for NLP.
    """
    if not html_text:
        return ''
    # Remove style and script sections
    clean = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    # Replace common block elements with newlines
    clean = re.sub(r'</?(div|p|br|li|h[1-6]|tr)[^>]*>', '\n', clean, flags=re.IGNORECASE)
    # Remove all remaining tags
    clean = re.sub(r'<[^>]+>', '', clean)
    # Decode HTML entities
    clean = unescape(clean)
    # Collapse whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def strip_quoted_reply(text: str) -> str:
    """
    Remove quoted reply lines (lines starting with >).
    Strips Gmail-style 'On ... wrote:' blocks.
    """
    if not text:
        return ''

    lines = text.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()
        # Skip quote markers
        if stripped.startswith('>'):
            continue
        # Skip "On ... wrote:" headers
        if re.match(r'^On\s+.+\s+wrote:\s*$', stripped):
            break
        result.append(line)

    return '\n'.join(result).strip()


def strip_signature(text: str) -> str:
    """
    Remove email signatures.
    Looks for common signature delimiters: '-- ', '--', 'Best regards', etc.
    """
    if not text:
        return ''

    # Standard signature delimiter (dash-dash-space)
    if '\n-- \n' in text:
        return text.split('\n-- \n')[0]

    # Common signature keywords
    sig_patterns = [
        r'\n--\s*\n',
        r'\nBest regards',
        r'\nRegards',
        r'\nSincerely',
        r'\nCheers',
        r'\nThanks',
        r'\nSent from my',
    ]

    for pattern in sig_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return text[:match.start()]

    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces."""
    return re.sub(r'\s+', ' ', text).strip()


def extract_clean_body(email_instance) -> str:
    """
    Extract fully cleaned plain text from an Email instance,
    ready for LLM input.

    Applies the full pipeline: HTML strip, quoted-reply removal,
    signature removal, and whitespace normalization.
    Truncates to 4000 characters to fit LLM context windows.

    Args:
        email_instance: An Email model instance.

    Returns:
        Cleaned plain text string, or empty string if no body.
    """
    text = email_instance.body_text or ''
    if not text:
        return email_instance.snippet or ''

    text = strip_html(text)
    text = strip_quoted_reply(text)
    text = strip_signature(text)
    text = normalize_whitespace(text)
    # Truncate for LLM context efficiency
    if len(text) > 4000:
        text = text[:4000]
    return text


def extract_email_features(email_instance) -> str:
    """
    Extract a normalized feature string from an Email instance.

    Combines sender domain, subject, and body snippet into a single
    string for the classifier.

    Args:
        email_instance: An Email model instance.

    Returns:
        A normalized string suitable for NLP embedding/classification.
    """
    parts = []

    # Sender domain (strong signal)
    sender = email_instance.sender_email
    if sender and '@' in sender:
        domain = sender.split('@')[1]
        parts.append(f"sender_domain:{domain}")

    # Subject
    if email_instance.subject:
        parts.append(f"subject:{email_instance.subject.strip()}")

    # Body text (cleaned)
    body = email_instance.body_text or ''
    if body:
        cleaned = strip_html(body)
        cleaned = strip_quoted_reply(cleaned)
        cleaned = strip_signature(cleaned)
        cleaned = normalize_whitespace(cleaned)
        # Take first 1000 chars for efficiency
        if len(cleaned) > 1000:
            cleaned = cleaned[:1000]
        parts.append(f"body:{cleaned}")

    # Snippet fallback
    if not body and email_instance.snippet:
        parts.append(f"snippet:{email_instance.snippet}")

    return ' '.join(parts)
