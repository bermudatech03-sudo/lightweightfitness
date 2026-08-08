from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    NotificationViewSet, VapidPublicKeyView, PushSubscribeView,
    PushUnsubscribeView, MyPushSubscriptionsView,
    MemberPushLinkView, MemberPushSubscriptionsView, RevokePushSubscriptionView,
)

router = DefaultRouter()
router.register("", NotificationViewSet, basename="notification")
urlpatterns = [
    path("push/vapid-key/",    VapidPublicKeyView.as_view(),      name="push-vapid-key"),
    path("push/subscribe/",    PushSubscribeView.as_view(),       name="push-subscribe"),
    path("push/unsubscribe/",  PushUnsubscribeView.as_view(),     name="push-unsubscribe"),
    path("push/subscriptions/", MyPushSubscriptionsView.as_view(), name="push-subscriptions"),
    path("push/member/<int:member_id>/link/",          MemberPushLinkView.as_view(),          name="push-member-link"),
    path("push/member/<int:member_id>/subscriptions/", MemberPushSubscriptionsView.as_view(), name="push-member-subscriptions"),
    path("push/subscriptions/<int:subscription_id>/revoke/", RevokePushSubscriptionView.as_view(), name="push-revoke"),
    path("", include(router.urls)),
]