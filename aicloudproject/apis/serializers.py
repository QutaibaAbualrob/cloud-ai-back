"""
DRF serializers for the CloudAI REST API.

Each serializer maps a model to JSON for the API, handling
read/write/validation. Some serializers are read-only (FeedbackLog)
while others support full CRUD.
"""

from rest_framework import serializers
from django.contrib.auth.models import User

from .models import UserProfile, EmailAccount, Category, Email, FeedbackLog


# ── auth / profile ────────────────────────────────────────────────


class UserSerializer(serializers.ModelSerializer):
    """Minimal user representation for nested display."""

    class Meta:
        model = User
        fields = ["id", "username", "email"]


class UserProfileSerializer(serializers.ModelSerializer):
    """Read/write profile with nested user info."""

    user = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            "id", "user", "subscription_tier",
            "sync_enabled", "sync_interval_minutes", "created_at",
        ]
        read_only_fields = ["user", "created_at"]


# ── email accounts ────────────────────────────────────────────────


class EmailAccountSerializer(serializers.ModelSerializer):
    """
    Email account with provider credentials.

    The IMAP password is write-only: it is accepted on create/update
    but never included in API responses.
    """

    class Meta:
        model = EmailAccount
        fields = [
            "id", "provider", "email_address", "label",
            "imap_host", "imap_port", "imap_username", "imap_use_ssl",
            "last_synced_at", "is_active", "created_at",
        ]
        read_only_fields = ["id", "last_synced_at", "created_at"]
        extra_kwargs = {
            "imap_password": {"write_only": True},
        }

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


# ── categories ────────────────────────────────────────────────────


class CategorySerializer(serializers.ModelSerializer):
    """Category with a computed email count for UI badges."""

    email_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id", "name", "slug", "color", "icon",
            "is_builtin", "display_order", "email_count", "created_at",
        ]
        read_only_fields = ["id", "is_builtin", "created_at"]

    def get_email_count(self, obj):
        return obj.emails.count()

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


# ── emails ────────────────────────────────────────────────────────


class EmailListSerializer(serializers.ModelSerializer):
    """Compact serializer for email list views — no full body."""

    category_name = serializers.CharField(
        source="category.name", read_only=True, default=None
    )
    category_color = serializers.CharField(
        source="category.color", read_only=True, default=None
    )

    class Meta:
        model = Email
        fields = [
            "id", "sender_name", "sender_email", "subject",
            "snippet", "received_at",
            "category", "category_name", "category_color",
            "confidence_score", "is_ai_classified",
            "is_read", "is_archived",
        ]


class EmailDetailSerializer(serializers.ModelSerializer):
    """Full serializer for email detail — includes body content."""

    category_name = serializers.CharField(
        source="category.name", read_only=True, default=None
    )
    category_color = serializers.CharField(
        source="category.color", read_only=True, default=None
    )
    account_email = serializers.CharField(
        source="email_account.email_address", read_only=True
    )

    class Meta:
        model = Email
        fields = [
            "id",
            "sender_name", "sender_email", "recipient_email",
            "subject", "body_text", "body_html", "snippet",
            "received_at",
            "category", "category_name", "category_color",
            "confidence_score", "is_ai_classified",
            "is_read", "is_archived",
            "account_email", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EmailCategoryUpdateSerializer(serializers.Serializer):
    """Lightweight serializer for the PATCH /api/emails/<id>/category/ action."""

    category_id = serializers.IntegerField(required=True)


# ── feedback ──────────────────────────────────────────────────────


class FeedbackLogSerializer(serializers.ModelSerializer):
    """Read-only feedback history with resolved category names."""

    predicted_category_name = serializers.CharField(
        source="predicted_category.name", read_only=True, default=None
    )
    corrected_category_name = serializers.CharField(
        source="corrected_category.name", read_only=True, default=None
    )

    class Meta:
        model = FeedbackLog
        fields = [
            "id", "email",
            "predicted_category", "predicted_category_name",
            "corrected_category", "corrected_category_name",
            "email_subject", "email_sender",
            "is_applied", "created_at",
        ]
        read_only_fields = "__all__"
