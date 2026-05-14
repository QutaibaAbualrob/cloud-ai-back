"""
API URL configuration for the CloudAI platform.

All endpoints are registered through a single DefaultRouter, which
automatically generates standard CRUD routes (list, create, retrieve,
update, partial_update, destroy) plus any custom @action routes
defined on the ViewSets.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    UserProfileViewSet,
    EmailAccountViewSet,
    CategoryViewSet,
    EmailViewSet,
    FeedbackLogViewSet,
    AnalyticsViewSet,
)

router = DefaultRouter()
router.register(r"profile", UserProfileViewSet, basename="profile")
router.register(r"accounts", EmailAccountViewSet, basename="accounts")
router.register(r"categories", CategoryViewSet, basename="categories")
router.register(r"emails", EmailViewSet, basename="emails")
router.register(r"feedback", FeedbackLogViewSet, basename="feedback")
router.register(r"analytics", AnalyticsViewSet, basename="analytics")

urlpatterns = [
    path("", include(router.urls)),
]
