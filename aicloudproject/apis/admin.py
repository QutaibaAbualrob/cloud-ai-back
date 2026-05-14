from django.contrib import admin

from .models import UserProfile, EmailAccount, Category, Email, FeedbackLog


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "subscription_tier", "sync_enabled", "created_at"]
    list_filter = ["subscription_tier", "sync_enabled"]
    search_fields = ["user__username", "user__email"]


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ["email_address", "user", "provider", "is_active", "last_synced_at"]
    list_filter = ["provider", "is_active"]
    search_fields = ["email_address", "user__username"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "user", "is_builtin", "display_order"]
    list_filter = ["is_builtin"]
    search_fields = ["name", "user__username"]


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = [
        "subject_truncated", "sender_email", "user", "category",
        "confidence_score", "received_at", "is_ai_classified",
    ]
    list_filter = ["is_ai_classified", "is_read", "is_archived"]
    search_fields = ["subject", "sender_email", "sender_name", "body_text"]
    readonly_fields = ["created_at", "updated_at"]

    def subject_truncated(self, obj):
        return obj.subject[:60] if obj.subject else "(no subject)"


@admin.register(FeedbackLog)
class FeedbackLogAdmin(admin.ModelAdmin):
    list_display = [
        "id", "user", "predicted_category", "corrected_category",
        "is_applied", "created_at",
    ]
    list_filter = ["is_applied"]
    search_fields = ["user__username", "email_subject", "email_sender"]
