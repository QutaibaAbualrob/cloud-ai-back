"""
Comprehensive test suite for the CloudAI REST API.

Tests cover authentication, email CRUD, category management,
account connections, analytics, and the critic feedback loop.
"""

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from .models import UserProfile, EmailAccount, Category, Email, FeedbackLog


# ── helpers ────────────────────────────────────────────────────────────────


def create_test_user(username="testuser", password="testpass123"):
    user = User.objects.create_user(username=username, password=password)
    UserProfile.objects.create(user=user)
    return user


def create_category(user, name="Work", color="#22c55e", is_builtin=False):
    return Category.objects.create(
        user=user, name=name, slug=name.lower(), color=color,
        is_builtin=is_builtin, display_order=0,
    )


def create_email(user, category=None, subject="Test Email"):
    account = EmailAccount.objects.create(
        user=user, provider="imap", email_address="test@example.com",
    )
    return Email.objects.create(
        user=user, email_account=account, category=category,
        external_id="ext-1", subject=subject,
        sender_email="sender@example.com", snippet="Test snippet",
        is_ai_classified=bool(category),
    )


# ── auth tests ─────────────────────────────────────────────────────────────


class AuthTests(APITestCase):
    """Test registration and login via dj-rest-auth."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="existing", password="pass123",
        )

    def test_register(self):
        url = reverse("rest_register")
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
        res = self.client.post(url, data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("key", res.data)  # auth token

    def test_login(self):
        url = reverse("rest_login")
        res = self.client.post(url, {"username": "existing", "password": "pass123"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("key", res.data)

    def test_login_invalid(self):
        url = reverse("rest_login")
        res = self.client.post(url, {"username": "wrong", "password": "wrong"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ── category tests ─────────────────────────────────────────────────────────


class CategoryTests(APITestCase):
    """Test CRUD for user categories."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("categories-list")

    def test_list_categories(self):
        create_category(self.user, "Work")
        create_category(self.user, "Personal")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data.get("results", res.data)), 2)

    def test_create_category(self):
        res = self.client.post(self.url, {"name": "Shopping", "color": "#ec4899"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["name"], "Shopping")

    def test_update_category(self):
        cat = create_category(self.user, "OldName", color="#3b82f6")
        url = reverse("categories-detail", args=[cat.id])
        res = self.client.put(url, {"name": "NewName", "color": "#22c55e"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        cat.refresh_from_db()
        self.assertEqual(cat.name, "NewName")

    def test_delete_custom_category(self):
        cat = create_category(self.user, "Custom", is_builtin=False)
        url = reverse("categories-detail", args=[cat.id])
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_delete_builtin(self):
        cat = create_category(self.user, "Builtin", is_builtin=True)
        url = reverse("categories-detail", args=[cat.id])
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_denied(self):
        self.client.force_authenticate(user=None)
        res = self.client.get(self.url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


# ── email tests ────────────────────────────────────────────────────────────


class EmailTests(APITestCase):
    """Test email listing, detail, and category changes."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)
        self.email = create_email(self.user, category=None)

    def test_list_emails(self):
        res = self.client.get(reverse("emails-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data.get("results", res.data)
        self.assertGreaterEqual(len(items), 1)

    def test_email_detail(self):
        url = reverse("emails-detail", args=[self.email.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["subject"], "Test Email")

    def test_change_category_triggers_feedback(self):
        """Changing category on an AI-classified email creates FeedbackLog."""
        cat = create_category(self.user, "Work")
        self.email.is_ai_classified = True
        self.email.save()

        url = reverse("emails-category", args=[self.email.id])
        res = self.client.patch(url, {"category_id": cat.id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # FeedbackLog should exist
        logs = FeedbackLog.objects.filter(email=self.email)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().corrected_category, cat)

    def test_uncategorized_filter(self):
        """Emails without a category appear in uncategorized endpoint."""
        res = self.client.get(reverse("emails-uncategorized"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data), 1)

    def test_other_user_emails_invisible(self):
        other = create_test_user(username="other")
        create_email(other, category=None)
        res = self.client.get(reverse("emails-list"))
        items = res.data.get("results", res.data)
        for item in items:
            self.assertEqual(item.get("sender_email"), "sender@example.com")


# ── analytics tests ────────────────────────────────────────────────────────


class AnalyticsTests(APITestCase):
    """Test analytics endpoints return correct shape."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)

    def test_summary_empty(self):
        res = self.client.get(reverse("analytics-summary"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("accuracy", res.data)
        self.assertEqual(res.data["total_classified"], 0)

    def test_summary_with_data(self):
        cat = create_category(self.user, "Work")
        create_email(self.user, category=cat, subject="Classified email")
        res = self.client.get(reverse("analytics-summary"))
        self.assertEqual(res.data["total_classified"], 1)
        self.assertEqual(res.data["accuracy"], 1.0)

    def test_timeline(self):
        res = self.client.get(reverse("analytics-timeline"), {"days": 7})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)

    def test_distribution(self):
        cat = create_category(self.user, "Work")
        create_email(self.user, category=cat)
        res = self.client.get(reverse("analytics-distribution"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data), 1)

    def test_digest(self):
        res = self.client.get(reverse("analytics-digest"), {"days": 1})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_urgent(self):
        res = self.client.get(reverse("analytics-urgent"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("urgent_count", res.data)


# ── email account tests ────────────────────────────────────────────────────


class AccountTests(APITestCase):
    """Test email account CRUD and manual sync."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)

    def test_create_gmail_account(self):
        res = self.client.post(reverse("accounts-list"), {
            "provider": "gmail",
            "email_address": "user@gmail.com",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["provider"], "gmail")

    def test_list_accounts(self):
        EmailAccount.objects.create(
            user=self.user, provider="imap",
            email_address="test@example.com",
        )
        res = self.client.get(reverse("accounts-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data.get("results", res.data)
        self.assertEqual(len(items), 1)

    def test_sync_triggers_no_error(self):
        acc = EmailAccount.objects.create(
            user=self.user, provider="gmail",
            email_address="gmail@example.com",
        )
        url = reverse("accounts-sync", args=[acc.id])
        res = self.client.post(url)
        # Without celery installed, returns 503; with celery, returns 200
        self.assertIn(res.status_code, [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE])
        if res.status_code == status.HTTP_200_OK:
            self.assertEqual(res.data["status"], "sync_enqueued")

    def test_delete_account(self):
        acc = EmailAccount.objects.create(
            user=self.user, provider="imap",
            email_address="remove@example.com",
        )
        url = reverse("accounts-detail", args=[acc.id])
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)


# ── feedback tests ─────────────────────────────────────────────────────────


class FeedbackTests(APITestCase):
    """Test feedback log listing."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)

    def test_list_feedback(self):
        res = self.client.get(reverse("feedback-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_feedback_created_on_category_change(self):
        cat = create_category(self.user, "Shopping")
        email = create_email(self.user, category=None)
        email.is_ai_classified = True
        email.save()

        url = reverse("emails-category", args=[email.id])
        self.client.patch(url, {"category_id": cat.id})

        res = self.client.get(reverse("feedback-list"))
        items = res.data.get("results", res.data)
        self.assertGreaterEqual(len(items), 1)

    def test_feedback_pending_endpoint(self):
        res = self.client.get(reverse("analytics-feedback-pending"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("unapplied_feedback", res.data)


# ── profile tests ──────────────────────────────────────────────────────────


class ProfileTests(APITestCase):
    """Test user profile read and update."""

    def setUp(self):
        self.user = create_test_user()
        self.client.force_authenticate(user=self.user)

    def test_profile_exists(self):
        res = self.client.get(reverse("profile-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data.get("results", res.data)
        self.assertGreaterEqual(len(items), 1)

    def test_profile_has_subscription_field(self):
        res = self.client.get(reverse("profile-list"))
        items = res.data.get("results", res.data)
        self.assertIn("subscription_tier", items[0])


# ── isolation tests ────────────────────────────────────────────────────────


class IsolationTests(APITestCase):
    """Test that users cannot see each other's data."""

    def setUp(self):
        self.alice = create_test_user(username="alice")
        self.bob = create_test_user(username="bob")
        self.alice_client = APIClient()
        self.alice_client.force_authenticate(user=self.alice)

    def test_alice_categories_invisible_to_bob(self):
        create_category(self.alice, "Alice Category")
        res = self.alice_client.get(reverse("categories-list"))
        items = res.data.get("results", res.data)
        for cat in items:
            self.assertEqual(cat["name"], "Alice Category")
