import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.members.models import Member
from .models import Notification
from .serializers import NotificationSerializer
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