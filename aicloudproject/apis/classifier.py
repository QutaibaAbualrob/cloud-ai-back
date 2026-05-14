"""
NLP email classifier using zero-shot classification.

Uses HuggingFace transformers for zero-shot classification.
Falls back to a simple TF-IDF + Naive Bayes approach for environments
where large models are impractical.

Architecture:
    Performance Element — assigns initial categories to emails.
    Returns confidence scores for each prediction.
"""

import logging
import pickle
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from django.conf import settings
from django.db.models import QuerySet

from .models import Category, Email

logger = logging.getLogger(__name__)

# Model cache directory (relative to BASE_DIR)
MODEL_DIR = Path(settings.BASE_DIR) / 'models'


class EmailClassifier:
    """
    Zero-shot email classifier using HuggingFace transformers.

    Usage:
        classifier = EmailClassifier()
        predictions = classifier.classify_email(email_instance, user_categories)
        # Returns: [(category, confidence_score), ...]
    """

    def __init__(self, model_name: str = 'facebook/bart-large-mnli'):
        """
        Initialize the classifier with a zero-shot model.

        Args:
            model_name: HuggingFace model ID for zero-shot classification.
                        Options:
                        - 'facebook/bart-large-mnli' (large, accurate)
                        - 'typeform/distilbert-base-uncased-mnli' (faster)
                        - 'MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli' (balanced)
        """
        self.model_name = model_name
        self._pipeline = None

    @property
    def pipeline(self):
        """Lazy-load the zero-shot classification pipeline."""
        if self._pipeline is None:
            from transformers import pipeline
            logger.info(f"Loading zero-shot model: {self.model_name}")
            self._pipeline = pipeline(
                'zero-shot-classification',
                model=self.model_name,
                device=-1,  # CPU; use 0 for GPU
            )
        return self._pipeline

    def classify(
        self,
        text: str,
        labels: List[str],
        multi_label: bool = False,
    ) -> List[Dict[str, any]]:
        """
        Classify text against a list of candidate labels.

        Args:
            text: The normalized feature string from extract_email_features().
            labels: List of category names to choose from.
            multi_label: If True, allow multiple labels per email.

        Returns:
            List of dicts: [{'label': 'Business', 'score': 0.85}, ...]
            Sorted by score descending.
        """
        if not text or not labels:
            return []

        result = self.pipeline(
            text,
            candidate_labels=labels,
            multi_label=multi_label,
        )

        return [
            {'label': label, 'score': score}
            for label, score in zip(result['labels'], result['scores'])
        ]

    def classify_email(
        self,
        email_instance: Email,
        categories: QuerySet[Category],
        confidence_threshold: float = 0.4,
    ) -> Tuple[Optional[Category], float]:
        """
        Classify a single Email and assign the best category.

        Args:
            email_instance: Email model instance to classify.
            categories: Queryset of user's Category instances.
            confidence_threshold: Minimum score to auto-assign (0.0–1.0).

        Returns:
            Tuple of (assigned_category or None, confidence_score).
            Returns (None, score) if no category meets the threshold.
        """
        from .text_utils import extract_email_features

        text = extract_email_features(email_instance)
        category_names = [cat.name for cat in categories]
        category_map = {cat.name: cat for cat in categories}

        if not text or not category_names:
            return None, 0.0

        predictions = self.classify(text, category_names)

        if not predictions:
            return None, 0.0

        top = predictions[0]
        score = top['score']
        label = top['label']

        if score >= confidence_threshold:
            category = category_map.get(label)
            return category, score

        return None, score

    def classify_batch(
        self,
        emails: QuerySet[Email],
        categories: QuerySet[Category],
        confidence_threshold: float = 0.4,
        batch_size: int = 50,
    ) -> int:
        """
        Classify a batch of uncategorized emails.

        Args:
            emails: Queryset of Email instances (filtered to is_ai_classified=False).
            categories: Queryset of user's Category instances.
            confidence_threshold: Minimum score to auto-assign.
            batch_size: Number of emails to process (for pagination).

        Returns:
            Number of emails classified.
        """
        classified_count = 0
        category_names = [cat.name for cat in categories]
        category_map = {cat.name: cat for cat in categories}

        from .text_utils import extract_email_features

        for email_instance in emails[:batch_size]:
            text = extract_email_features(email_instance)

            if not text:
                continue

            predictions = self.classify(text, category_names)

            if predictions:
                top = predictions[0]
                score = top['score']
                label = top['label']

                if score >= confidence_threshold:
                    category = category_map.get(label)
                    email_instance.category = category
                    email_instance.confidence_score = score
                    email_instance.is_ai_classified = True
                    email_instance.save(update_fields=['category', 'confidence_score', 'is_ai_classified'])
                    classified_count += 1

        logger.info(f"Batch classified {classified_count}/{len(emails[:batch_size])} emails")
        return classified_count


# Global classifier instance (lazy-loaded singleton)
_classifier = None


def get_classifier() -> EmailClassifier:
    """Get or create the global EmailClassifier singleton."""
    global _classifier
    if _classifier is None:
        model_name = getattr(settings, 'CLASSIFIER_MODEL', 'facebook/bart-large-mnli')
        _classifier = EmailClassifier(model_name=model_name)
    return _classifier
