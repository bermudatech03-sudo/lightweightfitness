import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.members.models import Member
from .models import Notification, PushSubscription
from .serializers import NotificationSerializer, PushSubscriptionSerializer
from .utils import send_notification

logger = logging.getLogger(__name__)


class NotificationViewSet(viewsets.ModelViewSet):
    queryset         = Notification.objects.all()
    serializer_class = NotificationSerializer
    filterset_fields = ["status", "trigger_type"]
    ordering_fields  = ["created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        date = self.request.query_params.get("date")
        if date:
            qs = qs.filter(created_at__date=date)
        phone = self.request.query_params.get("phone")
        if phone:
            qs = qs.filter(recipient_phone__icontains=phone)
        return qs

    @action(detail=False, methods=["post"])
    def send_renewal_reminders(self, request):
        # Fire exactly 3 days before renewal date
        target = timezone.now().date() + timedelta(days=3)
        members = Member.objects.filter(
            status="active",
            renewal_date=target,
        )
        count = 0
        try:
            for m in members:
                send_notification(m, "renewal_remind")
                count += 1
        except Exception:
            logger.exception("NotificationViewSet.send_renewal_reminders: failed while sending reminders")
            raise
        logger.info(f"NotificationViewSet.send_renewal_reminders: sent {count} reminder(s) for renewal_date={target}")
        return Response({"sent": count, "message": f"Reminders sent to {count} members."})

    @action(detail=False, methods=["post"])
    def send_expiry_notices(self, request):
        today = timezone.now().date()
        # Auto-expire any active member past renewal
        expired_count = Member.objects.filter(
            status="active",
            renewal_date__lt=today,
        ).update(status="expired")

        # Send expiry notice exactly 3 days after expiry
        target = today - timedelta(days=3)
        members = Member.objects.filter(status="expired", renewal_date=target)
        count = 0
        try:
            for m in members:
                send_notification(m, "expiry")
                count += 1
        except Exception:
            logger.exception("NotificationViewSet.send_expiry_notices: failed while sending expiry notices")
            raise
        logger.info(
            f"NotificationViewSet.send_expiry_notices: auto-expired {expired_count} member(s), "
            f"sent {count} expiry notice(s) for renewal_date={target}"
        )
        return Response({"processed": count})

    @action(detail=False, methods=["post"])
    def manual(self, request):
        member_ids = request.data.get("member_ids", [])
        trigger    = request.data.get("trigger_type", "manual")
        logger.info(f"NotificationViewSet.manual: request to send trigger={trigger!r} to {len(member_ids)} member id(s)")
        count = 0
        try:
            for mid in member_ids:
                try:
                    m = Member.objects.get(pk=mid)
                    send_notification(m, trigger)
                    count += 1
                except Member.DoesNotExist:
                    logger.warning(f"NotificationViewSet.manual: member id {mid} not found, skipping")
        except Exception:
            logger.exception("NotificationViewSet.manual: failed while sending notifications")
            raise
        logger.info(f"NotificationViewSet.manual: completed, sent {count}/{len(member_ids)} notification(s)")
        return Response({"sent": count})


class VapidPublicKeyView(APIView):
    """
    Public VAPID key the frontend needs to call pushManager.subscribe(). Not
    secret — that's what "public key" means — so this is intentionally open
    (AllowAny), since the unauthenticated member opt-in page needs it too.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"publicKey": settings.VAPID_PUBLIC_KEY})


class PushSubscribeView(APIView):
    """
    Registers (or re-activates) a browser's push subscription for the logged-in
    admin/staff user. Called by the frontend right after the browser grants
    notification permission and returns a PushSubscription object.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data     = request.data
        endpoint = data.get("endpoint")
        keys     = data.get("keys") or {}
        p256dh   = keys.get("p256dh")
        auth     = keys.get("auth")
        if not (endpoint and p256dh and auth):
            logger.warning(f"PushSubscribeView: rejected — missing endpoint/keys (user={request.user.username})")
            return Response({"detail": "endpoint and keys.p256dh/keys.auth are required."}, status=400)

        sub, created = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user":       request.user,
                "p256dh":     p256dh,
                "auth":       auth,
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
                "is_active":  True,
            },
        )
        logger.info(
            f"PushSubscribeView: {'created' if created else 're-activated'} subscription "
            f"id={sub.pk} for user={request.user.username}"
        )
        return Response({"id": sub.id, "created": created}, status=201 if created else 200)


class PushUnsubscribeView(APIView):
    """Deactivates a browser's push subscription (soft — row is kept, is_active=False)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get("endpoint")
        if not endpoint:
            return Response({"detail": "endpoint is required."}, status=400)
        updated = PushSubscription.objects.filter(endpoint=endpoint).update(is_active=False)
        logger.info(f"PushUnsubscribeView: deactivated {updated} subscription(s) (user={request.user.username})")
        return Response({"deactivated": updated})


class MyPushSubscriptionsView(APIView):
    """Lists the logged-in user's active subscriptions — lets Settings show what's enabled."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        subs = PushSubscription.objects.filter(user=request.user, is_active=True)
        return Response(PushSubscriptionSerializer(subs, many=True).data)


class MemberPushLinkView(APIView):
    """
    Phase 2: admin scans the QR the member's opt-in page generated (raw
    endpoint/keys/user_agent — the member's browser never talks to this
    backend directly) and links it to that member's profile here. Requires
    an authenticated staff/admin session — the member never calls this.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, member_id):
        from apps.members.models import Member
        try:
            member = Member.objects.get(pk=member_id)
        except Member.DoesNotExist:
            return Response({"detail": "Member not found."}, status=404)

        data     = request.data
        endpoint = data.get("endpoint")
        keys     = data.get("keys") or {}
        p256dh   = keys.get("p256dh")
        auth     = keys.get("auth")
        if not (endpoint and p256dh and auth):
            logger.warning(f"MemberPushLinkView: rejected — missing endpoint/keys (member_id={member_id})")
            return Response({"detail": "endpoint and keys.p256dh/keys.auth are required."}, status=400)

        sub, created = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "member":     member,
                "user":       None,
                "p256dh":     p256dh,
                "auth":       auth,
                "user_agent": data.get("user_agent", "")[:255],
                "is_active":  True,
            },
        )
        logger.info(
            f"MemberPushLinkView: {'created' if created else 're-linked'} subscription "
            f"id={sub.pk} for member={member.id} ({member.name}), linked by {request.user.username}"
        )
        return Response({"id": sub.id, "created": created}, status=201 if created else 200)


class MemberPushSubscriptionsView(APIView):
    """Lists a specific member's active subscriptions — powers the 'linked devices' list on their profile."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, member_id):
        subs = PushSubscription.objects.filter(member_id=member_id, is_active=True)
        return Response(PushSubscriptionSerializer(subs, many=True).data)


class RevokePushSubscriptionView(APIView):
    """
    Admin-side revoke by subscription id (as opposed to PushUnsubscribeView,
    which is the self-service endpoint-based one for a user's own browser).
    Works for either a user- or member-linked subscription.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, subscription_id):
        updated = PushSubscription.objects.filter(pk=subscription_id).update(is_active=False)
        logger.info(
            f"RevokePushSubscriptionView: deactivated subscription id={subscription_id} "
            f"(updated={updated}, by {request.user.username})"
        )
        return Response({"deactivated": updated})