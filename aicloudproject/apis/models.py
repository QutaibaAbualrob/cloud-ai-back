"""
Core data models for the CloudAI email intelligence platform.

Models:
    UserProfile   — extends Django User with SaaS-specific fields
    EmailAccount  — connected email accounts (Gmail OAuth or IMAP)
    Category      — user-specific inbox categories (Business, Work, Family, etc.)
    Email         — ingested email with parsed fields and AI-assigned category
    FeedbackLog   — critic evidence: manual category corrections for the learning loop
"""

from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """
    Extends the built-in User model with SaaS-specific profile data.
    One-to-one relationship ensures each user has exactly one profile.
    """

    SUBSCRIPTION_TIERS = [
        ("free", "Free"),
        ("pro", "Pro"),
        ("enterprise", "Enterprise"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile"
    )
    subscription_tier = models.CharField(
        max_length=20, choices=SUBSCRIPTION_TIERS, default="free"
    )
    sync_enabled = models.BooleanField(default=True)
    sync_interval_minutes = models.PositiveIntegerField(default=15)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.username} ({self.subscription_tier})"


class EmailAccount(models.Model):
    """
    A connected email account for a user.
    Supports Gmail (OAuth 2.0) and generic IMAP accounts.

    Security note: access_token, refresh_token, and imap_password should be
    encrypted at rest in production (e.g. django-fernet-fields or AWS KMS).
    """

    PROVIDER_CHOICES = [
        ("gmail", "Gmail (OAuth)"),
        ("outlook", "Outlook / Office 365"),
        ("imap", "Generic IMAP"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_accounts"
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    email_address = models.EmailField()
    label = models.CharField(max_length=100, blank=True, help_text="User-friendly name for this account")

    # OAuth fields (used for Gmail / Outlook)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)

    # IMAP fields (used for generic IMAP)
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(null=True, blank=True)
    imap_username = models.CharField(max_length=255, blank=True)
    imap_password = models.CharField(max_length=255, blank=True)  # encrypt in production
    imap_use_ssl = models.BooleanField(default=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "email_address")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email_address} ({self.provider})"


class Category(models.Model):
    """
    A user-specific email category.
    Built-in defaults are created per-user. Users can add custom categories.
    """

    # Built-in category slugs — aligned with multi-inbox intelligence use case
    BUILTIN_SLUGS = ["work", "personal", "finance", "education", "notifications", "promotions", "miscellaneous"]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50)
    color = models.CharField(
        max_length=7, default="#6B7280", help_text="Hex color code for UI badge"
    )
    icon = models.CharField(max_length=50, blank=True, help_text="Icon identifier for frontend")
    is_builtin = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "slug")]
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class Email(models.Model):
    """
    A single email ingested from a connected EmailAccount.
    Stores raw headers/body alongside parsed text for NLP processing.
    Linked to an AI-assigned Category with a confidence score.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="emails"
    )
    email_account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="emails"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emails",
    )

    # External identifiers
    external_id = models.CharField(
        max_length=500, blank=True, help_text="Provider-specific message ID"
    )
    thread_id = models.CharField(
        max_length=500, blank=True, help_text="Email thread identifier"
    )

    # Parsed headers
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField()
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=1000, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    # Content
    body_text = models.TextField(blank=True, help_text="Plain-text body for NLP processing")
    body_html = models.TextField(blank=True, help_text="Original HTML body")
    snippet = models.CharField(max_length=300, blank=True)

    # Gmail labels / categories from the provider
    gmail_labels = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Provider label IDs from Gmail"
            " (e.g. ['INBOX', 'IMPORTANT', 'CATEGORY_PROMOTIONS'])"
        ),
    )

    # LLM-generated summary
    summary = models.TextField(
        blank=True, help_text="AI-generated one-sentence summary of the email content"
    )

    # Priority / urgency / deadline (extracted by LLM)
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, blank=True, default="",
        help_text="AI-assigned priority: low / medium / high"
    )
    is_urgent = models.BooleanField(
        default=False, help_text="AI-flagged as urgent or time-sensitive"
    )
    has_deadline = models.BooleanField(
        default=False, help_text="Whether the email mentions a deadline or due date"
    )
    deadline_date = models.DateTimeField(
        null=True, blank=True, help_text="Extracted deadline or due date if present"
    )
    action_items = models.TextField(
        blank=True, help_text="AI-extracted action items, tasks, or next steps (JSON list or plain text)"
    )

    # AI classification metadata
    confidence_score = models.FloatField(
        null=True, blank=True, help_text="0.0–1.0 confidence from AI classifier"
    )
    is_ai_classified = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "category"]),
            models.Index(fields=["user", "received_at"]),
            models.Index(fields=["external_id"]),
        ]

    def __str__(self):
        return f"{self.subject[:60]} — {self.sender_email}"


class FeedbackLog(models.Model):
    """
    Critic evidence: records when a user manually changes an email's category.
    Each entry stores the features that led to the original prediction and the
    corrected category, enabling the Learning Element to update its internal rules.
    """

    email = models.ForeignKey(
        Email, on_delete=models.CASCADE, related_name="feedback_events"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="feedback_events"
    )

    # What the AI predicted vs what the user chose
    predicted_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="predicted_feedback",
    )
    corrected_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrected_feedback",
    )

    # Snapshot of email features at time of correction (for retraining)
    email_subject = models.CharField(max_length=1000, blank=True)
    email_sender = models.EmailField(blank=True)
    email_snippet = models.CharField(max_length=300, blank=True)

    # Metadata
    is_applied = models.BooleanField(
        default=False, help_text="Whether this feedback has been incorporated into preference memory"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_applied"]),
        ]

    def __str__(self):
        return f"Feedback #{self.id}: {self.predicted_category} → {self.corrected_category}"


class EmailThread(models.Model):
    """
    Tracks the context and running summary of an email conversation thread.

    Updated as new emails arrive in the same thread. Provides the LLM
    with conversation history so it can understand evolving topics,
    ongoing discussions, and context across messages.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="threads"
    )
    thread_id = models.CharField(
        max_length=500, help_text="Provider-specific thread identifier (from Gmail)"
    )
    email_account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="threads"
    )

    # Latest subject line (may change as thread evolves)
    subject = models.CharField(max_length=1000, blank=True)

    # Participants tracked as comma-separated emails (e.g. "alice@co, bob@co")
    participants = models.TextField(blank=True)

    # Running summary — updated by LLM digest task as new emails arrive
    summary = models.TextField(
        blank=True, help_text="AI-generated running summary of the entire thread"
    )

    # Latest state
    latest_received_at = models.DateTimeField(null=True, blank=True)
    email_count = models.PositiveIntegerField(default=0, help_text="Number of emails in this thread")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "thread_id")]
        ordering = ["-latest_received_at"]
        indexes = [
            models.Index(fields=["user", "latest_received_at"]),
        ]

    def __str__(self):
        return f"Thread #{self.thread_id[:20]} — {self.subject[:50]}"
