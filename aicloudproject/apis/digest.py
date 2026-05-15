"""
Digest generation: aggregates email summaries into daily and category-based digests.

Uses the LLM API to synthesise per-email summaries into higher-level insights:
- Daily overview — what happened across all inboxes today
- Category summaries — what happened in each category
- Urgent items — action items and deadlines needing attention
- Thread context — running summaries per conversation thread

All context is stored in the EmailThread model and refreshed as new emails arrive.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count, Q

from .models import Email, EmailThread, Category
from .classifier import _llm_complete

logger = logging.getLogger(__name__)


# ── thread context updates ────────────────────────────────────────


def update_thread_context(email_instance: Email) -> Optional[EmailThread]:
    """
    Update or create an EmailThread with the latest email's content.

    Called after an email is classified. Updates the thread's running
    summary by asking the LLM to merge the existing summary with the
    new email's summary.
    """
    if not email_instance.thread_id:
        return None

    thread, created = EmailThread.objects.get_or_create(
        user=email_instance.user,
        thread_id=email_instance.thread_id,
        defaults={
            "email_account": email_instance.email_account,
            "subject": email_instance.subject or "",
            "participants": email_instance.sender_email,
            "summary": email_instance.summary or "",
            "latest_received_at": email_instance.received_at,
            "email_count": 1,
        },
    )

    if not created:
        # Update existing thread
        thread.subject = email_instance.subject or thread.subject
        thread.latest_received_at = email_instance.received_at or thread.latest_received_at
        thread.email_count += 1

        # Track unique participants
        existing = set(thread.participants.split(", ")) if thread.participants else set()
        if email_instance.sender_email:
            existing.add(email_instance.sender_email)
        thread.participants = ", ".join(sorted(existing))

        # If both old and new summaries exist, merge via LLM
        if thread.summary and email_instance.summary:
            merged = _merge_thread_summaries(
                thread.subject,
                thread.summary,
                email_instance.summary,
                email_instance.sender_email,
            )
            if merged:
                thread.summary = merged
        elif email_instance.summary and not thread.summary:
            thread.summary = email_instance.summary

        thread.save(update_fields=[
            "subject", "latest_received_at", "email_count",
            "participants", "summary", "updated_at",
        ])

    return thread


def _merge_thread_summaries(
    subject: str,
    existing_summary: str,
    new_summary: str,
    sender: str,
) -> Optional[str]:
    """Ask the LLM to merge an existing thread summary with a new email summary."""
    prompt = (
        f"Thread subject: {subject}\n\n"
        f"Existing context: {existing_summary}\n\n"
        f"New email from {sender}: {new_summary}\n\n"
        f"Return a single concise sentence that merges the existing context "
        f"with the new information, preserving key details from both."
    )
    system = "You are a thread summariser. Return a single sentence, no JSON, no formatting."
    return _llm_complete(system, prompt)


# ── digest generation ──────────────────────────────────────────────

DIGEST_PROMPT = """\
You are a multi-inbox intelligence assistant generating a daily digest.
Synthesise the following email summaries into a structured overview.

Return a JSON object with these fields:
  - "daily_overview": 2-3 sentence summary of the most important events.
  - "urgent_items": list of strings — items requiring immediate attention.
  - "key_deadlines": list of strings — upcoming deadlines or due dates.
  - "category_highlights": object mapping category names to 1-sentence highlights.
  - "action_item_count": integer — total action items across all emails.
  - "urgent_count": integer — number of flagged urgent emails.

Respond with ONLY the JSON object.
"""


def generate_daily_digest(user: User, days: int = 1) -> Optional[dict]:
    """
    Generate a daily digest for a user from recent email summaries.

    Args:
        user: Django User instance.
        days: Lookback window (default 1 = today).

    Returns:
        Dict with digest fields, or None if no data.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    emails = Email.objects.filter(
        user=user,
        created_at__gte=since,
    ).exclude(summary="").order_by("-received_at")[:100]

    if not emails.exists():
        return None

    # Organise by category
    category_map: dict[str, List[str]] = {}
    urgent_items: List[str] = []
    deadlines: List[str] = []

    for email in emails:
        cat_name = email.category.name if email.category else "Uncategorized"
        if cat_name not in category_map:
            category_map[cat_name] = []
        category_map[cat_name].append(email.summary)

        if email.is_urgent and email.summary:
            urgent_items.append(f"[{cat_name}] {email.summary}")
        if email.has_deadline and email.summary:
            deadline_str = email.deadline_date.isoformat() if email.deadline_date else "soon"
            deadlines.append(f"[{deadline_str}] {email.summary}")

    # Build the user prompt
    lines = [f"Daily digest for {since.date().isoformat()}\n"]
    for cat, summaries in sorted(category_map.items()):
        lines.append(f"\n## {cat}")
        for s in summaries:
            lines.append(f"- {s}")

    lines.append(f"\n\nUrgent items ({len(urgent_items)}):")
    for item in urgent_items:
        lines.append(f"- {item}")

    lines.append(f"\n\nDeadlines ({len(deadlines)}):")
    for d in deadlines:
        lines.append(f"- {d}")

    user_prompt = "\n".join(lines)
    raw = _llm_complete(DIGEST_PROMPT, user_prompt)

    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse digest LLM response")
        return None


def generate_category_digest(user: User, category_slug: str, days: int = 7) -> Optional[str]:
    """
    Generate a category-specific summary for a user over a time window.

    Args:
        user: Django User instance.
        category_slug: Slug of the category to summarise.
        days: Lookback window.

    Returns:
        One-sentence summary string, or None if no data.
    """
    from django.utils.timezone import now

    since = now() - timedelta(days=days)
    emails = Email.objects.filter(
        user=user,
        category__slug=category_slug,
        created_at__gte=since,
    ).exclude(summary="").order_by("-received_at")[:50]

    if not emails.exists():
        return None

    summaries = "\n".join(f"- {e.summary}" for e in emails)
    prompt = (
        f"Summarise what happened in the '{category_slug}' category "
        f"over the last {days} days based on these email summaries:\n\n{summaries}\n\n"
        f"Return a single concise paragraph."
    )
    system = "You are a category summariser. Return one paragraph, no JSON."
    return _llm_complete(system, prompt)


# ── urgent count helper ────────────────────────────────────────────


def get_urgent_summary(user: User) -> List[dict]:
    """
    Get all emails flagged as urgent for a user, with metadata.

    Returns:
        List of dicts: {id, subject, summary, category_name, deadline_date, action_items}
    """
    emails = Email.objects.filter(
        user=user,
        is_urgent=True,
    ).order_by("-received_at")[:20]

    return [
        {
            "id": e.id,
            "subject": e.subject,
            "summary": e.summary,
            "category_name": e.category.name if e.category else None,
            "deadline_date": e.deadline_date.isoformat() if e.deadline_date else None,
            "action_items": e.action_items,
        }
        for e in emails
    ]
