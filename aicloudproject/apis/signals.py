"""
Critic component: detects manual category overrides and records feedback.

The Critic monitors Email saves and detects when a user manually changes
an email's category from an AI-assigned value to their own choice. Each
correction is recorded as a FeedbackLog entry for the Learning Element.

This implements the **Critic** sub-agent from the Cognitive Learning Agent
architecture — it provides the ground-truth signal that drives improvement.
"""

import logging
from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import Email, FeedbackLog

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Email)
def detect_category_override(sender, instance, **kwargs):
    """
    Pre-save signal: detect manual category changes on AI-classified emails.

    Fires *before* the Email is saved so we can compare the old category
    (from the database) with the new category (on the unsaved instance).

    Creates a FeedbackLog record when:
    1. This is an update (not a new email)
    2. The category field actually changed
    3. The *old* category was AI-assigned (is_ai_classified was True)
    4. No duplicate FeedbackLog already exists for this exact correction

    Skips all other saves to avoid noise.
    """
    # Skip new emails — no prior category to compare
    if instance.pk is None:
        return

    # Fetch the pre-save version from the database
    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    # Skip if the category didn't change
    if old_instance.category_id == instance.category_id:
        return

    # Only log corrections of AI-assigned categories
    # If the old email wasn't AI-classified, this is just user setup, not a correction
    if not old_instance.is_ai_classified:
        return

    # Avoid creating duplicate FeedbackLog records for the same correction
    # (handles multiple rapid saves or signal re-entrance)
    if FeedbackLog.objects.filter(
        email=instance,
        user=instance.user,
        predicted_category=old_instance.category,
        corrected_category=instance.category,
        is_applied=False,
    ).exists():
        return

    # Create the feedback record with a feature snapshot
    FeedbackLog.objects.create(
        email=instance,
        user=instance.user,
        predicted_category=old_instance.category,
        corrected_category=instance.category,
        email_subject=instance.subject or "",
        email_sender=instance.sender_email or "",
        email_snippet=instance.snippet or "",
    )

    logger.info(
        "Critic: user %s corrected email #%s: '%s' -> '%s'",
        instance.user.username,
        instance.pk,
        old_instance.category.name if old_instance.category else "None",
        instance.category.name if instance.category else "None",
    )
