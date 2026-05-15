"""
DRF ViewSets for the CloudAI REST API.

All ViewSets are user-scoped: the default queryset filters to
`request.user` so users can only access their own data.
Custom actions provide email recategorization, sync triggers,
analytics, and batch classification.
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from .models import UserProfile, EmailAccount, Category, Email, FeedbackLog
from .serializers import (
    UserProfileSerializer,
    EmailAccountSerializer,
    CategorySerializer,
    EmailListSerializer,
    EmailDetailSerializer,
    EmailCategoryUpdateSerializer,
    FeedbackLogSerializer,
)
from .permissions import IsOwner
from .metrics import (
    user_accuracy,
    accuracy_timeline,
    category_distribution,
    unapplied_feedback_count,
)
from .digest import (
    generate_daily_digest,
    generate_category_digest,
    get_urgent_summary,
)


# ── profile ────────────────────────────────────────────────────────


class UserProfileViewSet(viewsets.ModelViewSet):
    """
    Read/update the authenticated user's profile.
    Only one profile exists per user (created automatically).
    """

    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return UserProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# ── email accounts ────────────────────────────────────────────────


class EmailAccountViewSet(viewsets.ModelViewSet):
    """
    CRUD for connected email accounts.

    Custom action:
    - `POST /api/accounts/<id>/sync/` — trigger a manual email sync.
    """

    serializer_class = EmailAccountSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["provider", "is_active"]

    def get_queryset(self):
        return EmailAccount.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None):
        """Trigger a manual sync for this email account."""
        account = self.get_object()
        try:
            from .tasks import sync_account
            sync_account.delay(account.id)
            return Response(
                {"status": "sync_enqueued", "account_id": account.id}
            )
        except ImportError:
            return Response(
                {"status": "celery_not_available", "account_id": account.id},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# ── categories ────────────────────────────────────────────────────


class CategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD for user categories.

    Built-in categories (Business, Work, Family, etc.) are protected
    from deletion — only custom categories can be removed.
    """

    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.is_builtin:
            return Response(
                {"error": "Cannot delete built-in categories"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ── emails ────────────────────────────────────────────────────────


class EmailViewSet(viewsets.ModelViewSet):
    """
    CRUD for emails within the user's inbox.

    Uses a compact serializer for list views and a full serializer
    (with body text) for detail views.

    Custom actions:
    - `GET /api/emails/uncategorized/` — emails needing manual review
    - `PATCH /api/emails/<id>/category/` — change category (triggers critic)
    - `POST /api/emails/batch_categorize/` — trigger AI reclassification
    """

    permission_classes = [IsAuthenticated, IsOwner]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["category", "is_read", "is_archived", "is_ai_classified"]
    search_fields = ["subject", "sender_name", "sender_email", "body_text"]
    ordering_fields = ["received_at", "created_at", "confidence_score"]
    ordering = ["-received_at"]

    def get_queryset(self):
        return (
            Email.objects
            .filter(user=self.request.user)
            .select_related("category")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return EmailListSerializer
        return EmailDetailSerializer

    @action(detail=False, methods=["get"])
    def uncategorized(self, request):
        """
        Emails the AI couldn't confidently classify.
        These need manual categorization from the user.
        """
        emails = (
            self.get_queryset()
            .filter(is_ai_classified=False, category__isnull=True)
            .order_by("-received_at")[:50]
        )
        serializer = EmailListSerializer(emails, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"])
    def category(self, request, pk=None):
        """
        Change an email's category.

        If the email was previously AI-classified, the `pre_save` signal
        in `signals.py` detects the change and creates a FeedbackLog
        record for the Learning Element.
        """
        email = self.get_object()
        serializer = EmailCategoryUpdateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        category_id = serializer.validated_data["category_id"]

        try:
            category = Category.objects.get(id=category_id, user=request.user)
        except Category.DoesNotExist:
            return Response(
                {"error": "Category not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        email.category = category
        email.save(update_fields=["category", "updated_at"])

        return Response(EmailListSerializer(email).data)

    @action(detail=False, methods=["post"])
    def batch_categorize(self, request):
        """Trigger AI classification for all uncategorized emails."""
        try:
            from .tasks import classify_uncategorized_emails
            classify_uncategorized_emails.delay(request.user.id)
            return Response({"status": "classification_enqueued"})
        except ImportError:
            return Response(
                {"status": "celery_not_available"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# ── feedback ──────────────────────────────────────────────────────


class FeedbackLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only history of category corrections for this user."""

    serializer_class = FeedbackLogSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return FeedbackLog.objects.filter(user=self.request.user)


# ── analytics ─────────────────────────────────────────────────────


class AnalyticsViewSet(viewsets.ViewSet):
    """
    Read-only analytics about the AI learning loop.

    Actions are accessed at:
    - GET /api/analytics/summary/
    - GET /api/analytics/timeline/?days=30
    - GET /api/analytics/distribution/
    - GET /api/analytics/feedback_pending/
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Overall accuracy and statistics for the current user."""
        return Response(user_accuracy(request.user))

    @action(detail=False, methods=["get"])
    def timeline(self, request):
        """Daily accuracy time-series for charts."""
        days = int(request.query_params.get("days", 30))
        return Response(accuracy_timeline(request.user, days=days))

    @action(detail=False, methods=["get"])
    def distribution(self, request):
        """Category breakdown for pie charts."""
        return Response(category_distribution(request.user))

    @action(detail=False, methods=["get"])
    def digest(self, request):
        """Generate an on-demand daily digest for the current user."""
        days = int(request.query_params.get("days", 1))
        digest = generate_daily_digest(request.user, days=days)
        if not digest:
            return Response({"message": "No data for digest yet"})
        return Response(digest)

    @action(detail=False, methods=["get"])
    def category_digest(self, request):
        """Generate a category-specific summary."""
        slug = request.query_params.get("slug", "")
        if not slug:
            return Response({"error": "Missing 'slug' parameter"}, status=400)
        days = int(request.query_params.get("days", 7))
        result = generate_category_digest(request.user, slug, days=days)
        if not result:
            return Response({"message": "No data for this category yet"})
        return Response({"slug": slug, "summary": result})

    @action(detail=False, methods=["get"])
    def urgent(self, request):
        """Get all currently flagged urgent emails."""
        items = get_urgent_summary(request.user)
        return Response({"urgent_count": len(items), "items": items})

    @action(detail=False, methods=["get"])
    def feedback_pending(self, request):
        """Count of unapplied feedback records (not yet retrained)."""
        return Response({
            "unapplied_feedback": unapplied_feedback_count(request.user),
        })
