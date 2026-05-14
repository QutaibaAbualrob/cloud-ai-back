"""
Learning Element: retrains the per-user classifier from accumulated feedback.

The Learning Element collects FeedbackLog records that haven't yet been
applied, builds a training dataset of (email_features -> corrected_category)
pairs, and trains a lightweight per-user classifier using TF-IDF vectorization
+ Logistic Regression.

Architecture:
    Each user gets their own serialised model file on disk:
        models/user_{id}_classifier.pkl

    When a user has accumulated N or more unapplied corrections, the
    periodic `retrain_all_users()` task triggers per-user retraining.

    Once a model is trained, the consumed FeedbackLog records are marked
    `is_applied = True` so they aren't retrained on repeatedly.
"""

import logging
import pickle
from pathlib import Path
from typing import List, Tuple

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count

from .models import FeedbackLog

logger = logging.getLogger(__name__)

# Directory for per-user model files
MODEL_DIR = Path(settings.BASE_DIR) / "models"


class UserClassifier:
    """
    Lightweight per-user classifier trained on personal correction history.

    Uses a TF-IDF vectoriser + multinomial Logistic Regression for fast,
    CPU-friendly retraining. Models are serialised to disk and loaded
    on demand.

    Usage:
        clf = UserClassifier(user_id=42)
        if clf.load():
            category, confidence = clf.predict("some email text")
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.model_path = MODEL_DIR / f"user_{user_id}_classifier.pkl"
        self._vectorizer = None
        self._classifier = None
        self._labels: List[str] = []

    # ── persistence ─────────────────────────────────────────────

    def save(self) -> None:
        """Serialise the current model to disk."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump(
                {
                    "vectorizer": self._vectorizer,
                    "classifier": self._classifier,
                    "labels": self._labels,
                },
                f,
            )
        logger.debug("Saved classifier for user %s (%s)", self.user_id, self.model_path)

    def load(self) -> bool:
        """Load a previously-saved model from disk. Returns True on success."""
        if not self.model_path.exists():
            return False
        with open(self.model_path, "rb") as f:
            data = pickle.load(f)
        self._vectorizer = data["vectorizer"]
        self._classifier = data["classifier"]
        self._labels = data["labels"]
        logger.debug("Loaded classifier for user %s", self.user_id)
        return True

    def exists(self) -> bool:
        """Whether a serialised model file exists on disk."""
        return self.model_path.exists()

    # ── training ────────────────────────────────────────────────

    def train(self, texts: List[str], labels: List[str]) -> bool:
        """
        Train the classifier from parallel lists of texts and labels.

        Args:
            texts:  Feature strings (e.g. "sender_domain:example.com subject:Hello").
            labels: Corresponding corrected category names.

        Returns:
            True if training succeeded (at least 5 samples needed).
        """
        if len(texts) < 5:
            logger.warning(
                "User %s: insufficient training data (%s samples, need 5)",
                self.user_id,
                len(texts),
            )
            return False

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            stop_words="english",
        )
        X = self._vectorizer.fit_transform(texts)

        self._classifier = LogisticRegression(
            max_iter=1000,
            multi_class="multinomial",
            random_state=42,
        )
        self._classifier.fit(X, labels)
        self._labels = list(self._classifier.classes_)

        self.save()

        logger.info(
            "User %s: trained classifier with %s samples, %s classes",
            self.user_id,
            len(texts),
            len(self._labels),
        )
        return True

    # ── inference ───────────────────────────────────────────────

    def predict(self, text: str) -> Tuple[str, float]:
        """
        Predict the category for a piece of email text.

        Returns:
            (category_name, confidence_score) — score is 0.0–1.0.
            Returns ("", 0.0) if no model is loaded.
        """
        if self._classifier is None:
            return "", 0.0

        X = self._vectorizer.transform([text])
        probs = self._classifier.predict_proba(X)[0]
        best_idx = probs.argmax()
        return self._labels[best_idx], float(probs[best_idx])


# ── dataset helpers ──────────────────────────────────────────────

def build_training_dataset(user: User) -> Tuple[List[str], List[str]]:
    """
    Build a training dataset from unapplied FeedbackLog records for a user.

    Returns:
        (texts, labels) — parallel lists of feature strings and category names.
        Returns ([], []) if no unapplied feedback exists.
    """
    feedbacks = FeedbackLog.objects.filter(
        user=user,
        is_applied=False,
    ).select_related("corrected_category")

    texts: List[str] = []
    labels: List[str] = []

    for fb in feedbacks:
        # Build a composite feature string from the correction snapshot
        parts: List[str] = []
        if fb.email_sender and "@" in fb.email_sender:
            domain = fb.email_sender.split("@", 1)[1]
            parts.append(f"sender_domain:{domain}")
        if fb.email_subject:
            parts.append(f"subject:{fb.email_subject}")
        if fb.email_snippet:
            # Only use up to 500 chars of snippet for training
            snippet = fb.email_snippet[:500].replace("\n", " ")
            parts.append(f"snippet:{snippet}")

        text = " ".join(parts)
        if text and fb.corrected_category:
            texts.append(text)
            labels.append(fb.corrected_category.name)

    return texts, labels


# ── orchestration ────────────────────────────────────────────────

def retrain_for_user(user: User, min_samples: int = 10) -> bool:
    """
    Retrain the per-user classifier if enough unapplied feedback exists.

    Args:
        user: Django User instance.
        min_samples: Minimum unapplied FeedbackLog records to trigger training.

    Returns:
        True if retraining occurred, False otherwise.
    """
    texts, labels = build_training_dataset(user)

    if len(texts) < min_samples:
        return False

    classifier = UserClassifier(user.id)
    success = classifier.train(texts, labels)

    if success:
        # Mark all consumed feedback as applied so they aren't reused
        count = FeedbackLog.objects.filter(
            user=user,
            is_applied=False,
        ).update(is_applied=True)
        logger.info(
            "User %s: retrained and applied %s feedback records",
            user.username,
            count,
        )

    return success


def retrain_all_users(min_samples: int = 10, min_corrections: int = 1) -> int:
    """
    Periodic task entry point: check all users and retrain those with
    sufficient unapplied feedback.

    Args:
        min_samples: Minimum unapplied feedback records to trigger retraining.
        min_corrections: Minimum corrections to even consider a user
                         (optimisation filter to avoid querying everyone).

    Returns:
        Number of users whose classifiers were retrained.
    """
    users_with_feedback = (
        FeedbackLog.objects
        .filter(is_applied=False)
        .values("user")
        .annotate(count=Count("id"))
        .filter(count__gte=min_corrections)
    )

    retrained = 0
    for entry in users_with_feedback:
        try:
            user = User.objects.get(id=entry["user"])
            if retrain_for_user(user, min_samples=min_samples):
                retrained += 1
        except User.DoesNotExist:
            continue

    if retrained:
        logger.info("Retrained classifiers for %s users", retrained)
    else:
        logger.debug("No users needed retraining this cycle")

    return retrained
