"""
NLP email classifier using an LLM API for categorisation + summarisation.

Instead of running a local HuggingFace model, this module sends emails
to an LLM API (OpenAI-compatible) which returns:
  1. The most appropriate category from the user's category list
  2. A confidence score (0.0–1.0)
  3. A concise one-sentence summary of the email

Architecture:
    Performance Element — assigns categories + generates summaries via LLM.
    The LLM receives the user's category list as candidate labels plus
    optional preference hints from the UserPreferenceMemory.
"""

import json
import logging
from typing import List, Dict, Tuple, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from django.conf import settings
from django.db.models import QuerySet

from .models import Category, Email

logger = logging.getLogger(__name__)

# ── LLM client ────────────────────────────────────────────────────


def _llm_complete(system_prompt: str, user_prompt: str) -> Optional[str]:
    """
    Call an OpenAI-compatible LLM API and return the response text.

    Reads API endpoint and key from Django settings:
        LLM_API_URL  — e.g. 'https://api.openai.com/v1/chat/completions'
        LLM_API_KEY  — API key
        LLM_MODEL    — model name, e.g. 'gpt-4o-mini'

    Returns None on error.
    """
    api_url = getattr(settings, 'LLM_API_URL', None)
    api_key = getattr(settings, 'LLM_API_KEY', None)
    model = getattr(settings, 'LLM_MODEL', 'gpt-4o-mini')

    if not api_url or not api_key:
        logger.warning("LLM_API_URL or LLM_API_KEY not configured; skipping LLM call")
        return None

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }).encode("utf-8")

    req = Request(
        api_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            return data["choices"][0]["message"]["content"].strip()
    except URLError as e:
        logger.error("LLM API request failed: %s", e)
        return None
    except (KeyError, json.JSONDecodeError, IndexError) as e:
        logger.error("LLM API unexpected response: %s", e)
        return None


# ── prompts ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a multi-inbox intelligence assistant. For each email you receive, \
return a JSON object with the following fields:
  - "category": the best-matching category from the list provided.
  - "confidence": a float between 0.0 and 1.0 indicating how confident \
you are in this assignment.
  - "summary": a concise one-sentence summary of the email (max 20 words).
  - "priority": one of "low", "medium", or "high" — assess importance \
based on sender, urgency language, and content.
  - "is_urgent": boolean — true if the email requires immediate attention.
  - "has_deadline": boolean — true if a deadline or due date is mentioned.
  - "deadline_date": ISO 8601 datetime string or null — the exact deadline \
if mentioned (e.g. "2026-06-01T14:00:00").
  - "action_items": string — one sentence listing any tasks, next steps, \
or required actions. Empty string if none.

Rules:
- Choose ONLY from the provided category list. If none fit well, pick the \
closest match with a low confidence score (< 0.4) or "Miscellaneous" if \
truly uncategorisable.
- The "summary" should capture the key action or topic of the email.
- "priority" should reflect actual urgency: high for deadlines, manager \
requests, billing issues. Medium for important but not time-sensitive. \
Low for newsletters, notifications, spam-like content.
- "action_items" should be a single concise sentence, not a list.

Respond with ONLY the JSON object, no other text.
"""


def _build_user_prompt(
    subject: str,
    body: str,
    sender: str,
    category_names: List[str],
    preference_hints: str = "",
) -> str:
    """Build the user turn of the LLM prompt."""
    lines = [
        f"From: {sender}",
        f"Subject: {subject}",
        f"Body: {body}",
        "",
        f"Available categories: {', '.join(category_names)}",
    ]
    if preference_hints:
        lines.append(f"")
        lines.append(f"User preference hints:")
        lines.append(preference_hints)

    return "\n".join(lines)


def parse_llm_response(text: str) -> Optional[Dict[str, any]]:
    """
    Parse the LLM's JSON response.

    Tries to extract a JSON object from the response text, handling
    markdown code fences and extra whitespace.
    """
    cleaned = text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(cleaned)
        return {
            "category": data.get("category", ""),
            "confidence": float(data.get("confidence", 0.0)),
            "summary": data.get("summary", ""),
            "priority": data.get("priority", "low"),
            "is_urgent": bool(data.get("is_urgent", False)),
            "has_deadline": bool(data.get("has_deadline", False)),
            "deadline_date": data.get("deadline_date") or None,
            "action_items": data.get("action_items", ""),
        }
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse LLM response: %s — raw: %s", e, text[:200])
        return None


# ── classifier ─────────────────────────────────────────────────────


class EmailClassifier:
    """
    LLM-based email classifier.

    Calls an external LLM API to categorise and summarise each email.
    """

    def classify_email(
        self,
        email_instance: Email,
        categories: QuerySet[Category],
        preference_hints: str = "",
    ) -> dict:
        """
        Classify a single Email via the LLM API.

        Args:
            email_instance: Email model instance.
            categories: Queryset of the user's Category instances.
            preference_hints: Optional preference context string
                              (from UserPreferenceMemory).

        Returns:
            Dict with keys: category (Category|None), confidence (float),
            summary (str), priority (str), is_urgent (bool),
            has_deadline (bool), deadline_date (str|None), action_items (str).
        """
        from .text_utils import extract_clean_body

        body = extract_clean_body(email_instance)
        subject = email_instance.subject or "(no subject)"
        sender = email_instance.sender_email or "unknown"
        category_names = [cat.name for cat in categories]
        category_map = {cat.name: cat for cat in categories}

        default = {
            "category": None,
            "confidence": 0.0,
            "summary": "",
            "priority": "low",
            "is_urgent": False,
            "has_deadline": False,
            "deadline_date": None,
            "action_items": "",
        }

        if not category_names:
            return default

        user_prompt = _build_user_prompt(
            subject, body, sender, category_names, preference_hints
        )
        raw = _llm_complete(SYSTEM_PROMPT, user_prompt)

        if not raw:
            logger.warning("LLM returned no response for email #%s", email_instance.pk)
            return default

        result = parse_llm_response(raw)
        if not result:
            return default

        label = result["category"]
        confidence = result["confidence"]

        # Match the label to an actual Category object
        category_obj = category_map.get(label)
        if category_obj and confidence >= 0.4:
            result["category"] = category_obj
        else:
            result["category"] = None

        result["confidence"] = confidence
        return result

    def classify_batch(
        self,
        emails: QuerySet[Email],
        categories: QuerySet[Category],
        preference_hints: str = "",
        batch_size: int = 20,
    ) -> int:
        """
        Classify a batch of uncategorized emails via the LLM API.

        Each email is classified individually (one LLM call per email).
        Results are saved to the database including the AI-generated summary.

        Args:
            emails: Queryset of uncategorized Email instances.
            categories: Queryset of user's Category instances.
            preference_hints: Optional preference context from UserPreferenceMemory.
            batch_size: Maximum emails to process in this batch.

        Returns:
            Number of emails classified.
        """
        classified_count = 0
        misc_cat = next((c for c in categories if c.slug == "miscellaneous"), None)

        for email_instance in emails[:batch_size]:
            result = self.classify_email(
                email_instance, categories, preference_hints
            )

            cat = result["category"]
            score = result["confidence"]
            update_fields = ["updated_at"]

            # Assign category (fall back to Miscellaneous if low confidence)
            if cat and score >= 0.4:
                email_instance.category = cat
                email_instance.confidence_score = score
                email_instance.is_ai_classified = True
                update_fields.extend(["category", "confidence_score", "is_ai_classified"])
            elif misc_cat and score < 0.4:
                # Low confidence → assign to Miscellaneous catch-all
                email_instance.category = misc_cat
                email_instance.confidence_score = score
                email_instance.is_ai_classified = True
                update_fields.extend(["category", "confidence_score", "is_ai_classified"])

            # Save LLM-extracted fields
            if result.get("summary"):
                email_instance.summary = result["summary"]
                update_fields.append("summary")

            if result.get("priority"):
                email_instance.priority = result["priority"]
                update_fields.append("priority")

            email_instance.is_urgent = result.get("is_urgent", False)
            email_instance.has_deadline = result.get("has_deadline", False)
            update_fields.extend(["is_urgent", "has_deadline"])

            if result.get("deadline_date"):
                from datetime import datetime
                try:
                    email_instance.deadline_date = datetime.fromisoformat(
                        result["deadline_date"].replace("Z", "+00:00")
                    )
                    update_fields.append("deadline_date")
                except (ValueError, TypeError):
                    pass

            if result.get("action_items"):
                email_instance.action_items = result["action_items"]
                update_fields.append("action_items")

            if len(update_fields) > 1:
                email_instance.save(update_fields=update_fields)

            if cat or (misc_cat and score < 0.4):
                classified_count += 1

        logger.info(
            "LLM classified %s/%s emails in batch",
            classified_count,
            min(len(emails), batch_size),
        )
        return classified_count


# Global classifier instance (lazy singleton)
_classifier = None


def get_classifier() -> EmailClassifier:
    """Get or create the global EmailClassifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = EmailClassifier()
    return _classifier
