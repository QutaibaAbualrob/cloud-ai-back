"""
Celery tasks for background email synchronization and classifier retraining.
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

    Args:
        account_id: Primary key of EmailAccount to sync.
    """
    try:
        account = EmailAccount.objects.get(id=account_id, is_active=True)
    except EmailAccount.DoesNotExist:
        logger.warning(f"EmailAccount {account_id} not found or inactive")
        return

    sync_func = SYNC_STRATEGIES.get(account.provider)
    if sync_func is None:
        logger.warning(f"No sync strategy for provider: {account.provider}")
        return

    try:
        count = sync_func(account)
        logger.info(f"Synced {count} emails for account {account_id} ({account.email_address})")
        if count > 0:
            # Trigger classification for newly synced emails
            classify_uncategorized_emails.delay(account.user_id)
    except Exception as e:
        logger.error(f"Sync failed for account {account_id}: {e}", exc_info=True)


@shared_task
def sync_all_accounts():
    """
    Periodic task: sync all active email accounts.
    Triggered by Celery Beat every N minutes.
    """
    active_accounts = EmailAccount.objects.filter(is_active=True)

    for account in active_accounts:
        sync_account.delay(account.id)

    logger.info(f"Enqueued sync for {active_accounts.count()} accounts")


@shared_task
def classify_uncategorized_emails(user_id: int):
    """
    Classify all uncategorized emails for a user after a sync completes.
    """
    from django.contrib.auth.models import User
    from .models import Email, Category
    from .classifier import get_classifier

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

    classifier = get_classifier()
    count = classifier.classify_batch(uncategorized, categories)

    logger.info(f"Classified {count} emails for user {user.username}")


@shared_task
def retrain_classifiers():
    """
    Periodic task: retrain per-user classifiers based on accumulated feedback.

    Runs on Celery Beat schedule (e.g., daily at 3 AM).
    """
    from .learner import retrain_all_users
    count = retrain_all_users(min_samples=10)
    return f"Retrained {count} user classifiers"
