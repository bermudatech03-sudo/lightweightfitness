import logging
from datetime import timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from django.utils import timezone
from .models import Enquiry, EnquiryFollowup
from .serializers import EnquirySerializer

logger = logging.getLogger(__name__)


def _schedule_followups(enquiry):
    """Create 10 follow-up records: every 3 days for 30 days (day 3,6,...,30)."""
    base = timezone.localdate()
    followups = EnquiryFollowup.objects.bulk_create([
        EnquiryFollowup(enquiry=enquiry, scheduled_date=base + timedelta(days=3 * i))
        for i in range(1, 11)   # day 3, 6, 9 … 30
    ])
    logger.info(f"Scheduled {len(followups)} follow-ups for enquiry {enquiry.pk} ({enquiry.name})")


def _send_welcome(enquiry):
    from apps.notifications.models import Notification
    from apps.finances.gst_utils import get_setting
    gym_name = get_setting("GYM_NAME", "the Gym")
    gym_phone = get_setting("GYM_PHONE", "")

    phone = str(enquiry.phone or "").strip().replace(" ", "").replace("-", "")
    if phone and not phone.startswith("91"):
        phone = f"91{phone}"

    message = (
        f"Hi {enquiry.name}, thank you for your enquiry at {gym_name}! "
        f"We'd love to help you start your fitness journey. "
        f"Feel free to call us at {gym_phone} for more details. See you soon!"
    )

    logger.info(f"Sending welcome message to enquiry {enquiry.pk} ({enquiry.name}) at phone {phone}")

    Notification.objects.create(
        recipient_name=enquiry.name,
        recipient_phone=phone,
        channel="whatsapp",
        trigger_type="enquiry_welcome",
        message=message,
        status="pending",
    )


class EnquiryViewSet(viewsets.ModelViewSet):
    queryset = Enquiry.objects.prefetch_related("followups").all()
    serializer_class = EnquirySerializer
    filterset_fields = ["status"]
    search_fields = ["name", "phone"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enquiry = serializer.save()
        logger.info(f"Enquiry {enquiry.pk} created: name={enquiry.name}, phone={enquiry.phone}")
        _schedule_followups(enquiry)
        try:
            _send_welcome(enquiry)
        except Exception:
            logger.exception(f"Welcome message failed for enquiry {enquiry.pk} ({enquiry.name}) — continuing without blocking enquiry creation")
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def counts(self, request):
        """Status counts across ALL enquiries (not just the current page) for summary badges."""
        agg = Enquiry.objects.aggregate(
            total=Count("id"),
            new=Count("id", filter=Q(status="new")),
            followup=Count("id", filter=Q(status="followup")),
            converted=Count("id", filter=Q(status="converted")),
            lost=Count("id", filter=Q(status="lost")),
        )
        logger.info(f"Enquiry counts requested: {agg}")
        return Response(agg)
