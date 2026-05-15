"""
Analytics and accuracy metrics for the AI learning loop.

Exposes functions used by the analytics API endpoints (Phase 5) and
dashboard charts (Phase 6). All metrics are scoped per-user.

Accuracy definition:
    accuracy = 1 - (corrections / total_classified)
    where corrections is the number of FeedbackLog records created
    within the window, and total_classified is the number of emails
    the AI classified in that same window.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Email, FeedbackLog


def user_accuracy(user: User, days: int = 30) -> dict:
    """
    Calculate classification accuracy for a user over a time window.

    Args:
        user: Django User instance.
        days: Lookback window in days (default 30).

    Returns:
        {
            "total_classified": int,
            "corrections":       int,
            "accuracy":          float (0.0–1.0),
            "window_days":       int,
        }
    """
    since = timezone.now() - timedelta(days=days)

    total = Email.objects.filter(
        user=user,
        is_ai_classified=True,
        created_at__gte=since,
    ).count()

    corrections = FeedbackLog.objects.filter(
        user=user,
        created_at__gte=since,
    ).count()

    accuracy = 0.0
    if total > 0:
        accuracy = max(0.0, 1.0 - (corrections / total))

    return {
        "total_classified": total,
        "corrections": corrections,
        "accuracy": round(accuracy, 4),
        "window_days": days,
    }


def accuracy_timeline(user: User, days: int = 30) -> list:
    """
    Daily accuracy breakdown for a time-series chart.

    Args:
        user: Django User instance.
        days: Lookback window in days (default 30).

    Returns:
        List of dicts, one per day:
        [
            {
                "date":        "2026-05-01",
                "classified":  50,
                "corrections": 2,
                "accuracy":    0.96,
            },
            ...
        ]
    """
    since = timezone.now() - timedelta(days=days)

    # Classifications per day
    classified_qs = (
        Email.objects
        .filter(user=user, is_ai_classified=True, created_at__gte=since)
        .annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # Corrections per day
    corrections_qs = (
        FeedbackLog.objects
        .filter(user=user, created_at__gte=since)
        .annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # Index corrections by date for O(1) merging
    correction_map = {c["date"]: c["count"] for c in corrections_qs}

    timeline = []
    for entry in classified_qs:
        date = entry["date"]
        count = entry["count"]
        corrections_count = correction_map.get(date, 0)
        acc = max(0.0, 1.0 - (corrections_count / count)) if count > 0 else 0.0

        timeline.append({
            "date": date.isoformat(),
            "classified": count,
            "corrections": corrections_count,
            "accuracy": round(acc, 4),
        })

    return timeline


def category_distribution(user: User) -> list:
    """
    Count emails per category for a user.

    Returns:
        List of dicts, sorted by count descending:
        [
            {"category": "Business", "color": "#3B82F6", "count": 150},
            {"category": "Uncategorized", "color": "#6B7280", "count": 12},
            ...
        ]
    """
    distribution = (
        Email.objects
        .filter(user=user)
        .values("category__name", "category__color")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    return [
        {
            "category": d["category__name"] or "Uncategorized",
            "color": d["category__color"] or "#6B7280",
            "count": d["count"],
        }
        for d in distribution
    ]


def unapplied_feedback_count(user: User) -> int:
    """Number of FeedbackLog records not yet consumed by retraining."""
    return FeedbackLog.objects.filter(user=user, is_applied=False).count()
