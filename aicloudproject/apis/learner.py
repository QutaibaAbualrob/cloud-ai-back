"""
Learning Element: builds user preference memory from feedback evidence.

Instead of training ML models, the Learning Element collects FeedbackLog
records and builds structured "preference hints" for each user. These
hints are passed to the LLM API during classification so it can account
for the user's personal correction history.

Architecture:
    FeedbackLog records are treated as evidence of user preference, not
    as training data. The preference memory extracts patterns from
    corrections — for example: "when email is from amazon.com, user
    prefers 'Shopping' over 'Updates'".

    The hints are injected into the LLM prompt as additional context,
    guiding the LLM toward the user's preferred categorisation style.
"""

import logging
from collections import defaultdict
from typing import List

from django.contrib.auth.models import User
from django.db.models import Count

from .models import FeedbackLog

logger = logging.getLogger(__name__)


# ── preference memory ──────────────────────────────────────────────


class UserPreferenceMemory:
    """
    Persistent preference memory built from a user's correction history.

    Instead of retraining a model, this memory stores structured evidence
    about what categories the user prefers for specific sender domains,
    subjects, and other email features.

    The memory is exposed as a human-readable "hints" string that gets
    injected into the LLM prompt during classification.
    """

    def __init__(self, user: User):
        self.user = user
        self._hints: List[str] = []

    def build(self) -> None:
        """
        Query all FeedbackLog records for this user and extract
        preference patterns.
        """
        feedbacks = FeedbackLog.objects.filter(
            user=self.user,
        ).select_related("predicted_category", "corrected_category")

        if not feedbacks.exists():
            self._hints = []
            return

        # ── extract patterns ─────────────────────────────────────

        # Pattern 1: sender domain → preferred category
        domain_pref: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Pattern 2: predicted → corrected (user disagrees with AI)
        override_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Pattern 3: frequency of each corrected category
        category_freq: dict[str, int] = defaultdict(int)

        for fb in feedbacks:
            predicted = fb.predicted_category.name if fb.predicted_category else "None"
            corrected = fb.corrected_category.name if fb.corrected_category else "None"

            # Sender domain preference
            if fb.email_sender and "@" in fb.email_sender:
                domain = fb.email_sender.split("@", 1)[1].lower()
                domain_pref[domain][corrected] += 1

            # Override patterns
            if predicted != corrected:
                override_count[predicted][corrected] += 1

            # Category frequency
            if corrected != "None":
                category_freq[corrected] += 1

        # ── build hints ───────────────────────────────────────────

        hints: List[str] = []
        total = feedbacks.count()
        hints.append(f"Based on {total} past corrections by this user:")

        # Strong sender-domain preferences
        for domain, cats in sorted(domain_pref.items()):
            best_cat = max(cats, key=cats.get)
            best_count = cats[best_cat]
            if best_count >= 2:  # at least 2 corrections for confidence
                hints.append(
                    f"- Emails from {domain} → usually corrects to '{best_cat}' "
                    f"({best_count} time{'s' if best_count > 1 else ''})"
                )

        # Common overrides (user disagrees with AI on these)
        for predicted, corrections in sorted(override_count.items()):
            for corrected, count in sorted(corrections.items()):
                if count >= 2:
                    hints.append(
                        f"- Often moves '{predicted}' → '{corrected}' "
                        f"({count} time{'s' if count > 1 else ''})"
                    )

        # Limit hints to avoid overflowing the LLM prompt
        if len(hints) > 15:
            hints = hints[:15]
            hints.append(f"(and {len(hints) - 15} more patterns)")

        self._hints = hints
        logger.info(
            "Built preference memory for user %s: %s patterns from %s corrections",
            self.user.username,
            len(hints),
            total,
        )

    def get_hints(self) -> str:
        """Return the preference hints as a formatted string for LLM prompts."""
        return "\n".join(self._hints)

    @property
    def has_hints(self) -> bool:
        """Whether this memory contains any preference hints."""
        return len(self._hints) > 0


# ── orchestration ──────────────────────────────────────────────────


def build_preference_memory(user: User) -> UserPreferenceMemory:
    """
    Build preference memory for a single user.

    This is the equivalent of the old `retrain_for_user` — it refreshes
    the preference evidence from the latest FeedbackLog records.
    """
    memory = UserPreferenceMemory(user)
    memory.build()
    return memory


def refresh_all_memories(min_corrections: int = 1) -> int:
    """
    Periodic task entry point: identify users with feedback history
    and log that their preference memory is available.

    Unlike the old retraining approach, preference memory is built
    on-the-fly during classification. This function exists as a
    heartbeat/logging hook for the Celery Beat schedule.

    Args:
        min_corrections: Minimum corrections to log about.

    Returns:
        Number of users with available preference memory.
    """
    users_with_feedback = (
        FeedbackLog.objects
        .values("user")
        .annotate(count=Count("id"))
        .filter(count__gte=min_corrections)
    )

    user_count = users_with_feedback.count()
    if user_count:
        logger.info(
            "Preference memory available for %s users",
            user_count,
        )
    else:
        logger.debug("No users have accumulated feedback yet")

    return user_count
