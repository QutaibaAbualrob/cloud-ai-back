"""
Celery tasks for background email synchronisation, LLM classification,
and periodic preference memory refresh.
"""

import logging
from celery import shared_task

from .models import EmailAccount
from .gmail_sync import sync_gmail_account
from .imap_sync import sync_imap_account

logger = logging.getLogger(__name__)


SYNC_STRATEGIES = {
    'gmail': sync_gmail_account,
    'outlook': None,  # TODO: Microsoft Graph API
    'imap': sync_imap_account,
}


@shared_task
def sync_account(account_id: int):
    """
    Sync a single email account.

    After syncing, triggers LLM classification for any new emails.
    """
    try:
        account = EmailAccount.objects.get(id=account_id, is_active=True)
    except EmailAccount.DoesNotExist:
        logger.warning("EmailAccount %s not found or inactive", account_id)
        return

    sync_func = SYNC_STRATEGIES.get(account.provider)
    if sync_func is None:
        logger.warning("No sync strategy for provider: %s", account.provider)
        return

    try:
        count = sync_func(account)
        logger.info("Synced %s emails for account %s (%s)", count, account_id, account.email_address)
        if count > 0:
            # Trigger LLM classification + summarisation for new emails
            classify_uncategorized_emails.delay(account.user_id)
    except Exception as e:
        logger.error("Sync failed for account %s: %s", account_id, e, exc_info=True)
        raise  # re-raise so Celery marks the task as FAILURE (not "succeeded")


@shared_task
def sync_all_accounts():
    """
    Periodic task: sync all active email accounts.
    Triggered by Celery Beat every N minutes.
    """
    active_accounts = EmailAccount.objects.filter(is_active=True)

    for account in active_accounts:
        sync_account.delay(account.id)

    logger.info("Enqueued sync for %s accounts", active_accounts.count())


@shared_task
def classify_uncategorized_emails(user_id: int):
    """
    Classify all uncategorized emails for a user via the LLM API.

    The LLM both categorises and summarises each email. The user's
    preference memory (built from past FeedbackLog corrections) is
    injected into the LLM prompt as context for more personalised
    categorisation.
    """
    from django.contrib.auth.models import User
    from .models import Email, Category
    from .classifier import get_classifier
    from .learner import build_preference_memory

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    uncategorized = Email.objects.filter(
        user=user,
        is_ai_classified=False,
    ).order_by('-received_at')

    if not uncategorized.exists():
        return

    categories = Category.objects.filter(user=user)
    if not categories.exists():
        return

    # Build preference memory from the user's correction history
    memory = build_preference_memory(user)
    preference_hints = memory.get_hints() if memory.has_hints else ""

    # Classify via LLM — also generates summaries
    classifier = get_classifier()
    count = classifier.classify_batch(
        uncategorized,
        categories,
        preference_hints=preference_hints,
    )

    logger.info(
        "LLM classified %s emails for user %s (hints: %s)",
        count,
        user.username,
        "yes" if preference_hints else "no",
    )

    # Update thread context for each newly classified email
    from .digest import update_thread_context

    for email_instance in uncategorized[:count or 20]:
        if email_instance.thread_id:
            update_thread_context(email_instance)


@shared_task
def generate_daily_digest_for_all_users():
    """
    Periodic task: generate daily digests for all active users.

    Runs daily via Celery Beat. Digests are returned as structured
    dicts and logged. In future this could be emailed or pushed
    to the frontend.
    """
    from django.contrib.auth.models import User
    from .digest import generate_daily_digest

    active_users = User.objects.filter(
        emailaccount__is_active=True,
    ).distinct()

    generated = 0
    for user in active_users:
        try:
            digest = generate_daily_digest(user)
            if digest:
                generated += 1
                logger.info(
                    "Daily digest for user %s: %s urgent, %s action items",
                    user.username,
                    digest.get("urgent_count", 0),
                    digest.get("action_item_count", 0),
                )
        except Exception as e:
            logger.error("Digest failed for user %s: %s", user.username, e)

    logger.info("Generated daily digests for %s users", generated)


@shared_task
def refresh_preference_memories():
    """
    Periodic task: log which users have accumulated enough feedback
    for preference-aware classification.

    Preference memory is actually built on-the-fly during classification,
    so this task is primarily a heartbeat/logging hook. It replaces the
    old `retrain_classifiers` that trained scikit-learn models.
    """
    from .learner import refresh_all_memories
    count = refresh_all_memories(min_corrections=1)
    return f"Preference memory available for {count} users"
