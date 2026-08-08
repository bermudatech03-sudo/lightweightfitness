import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Notification
from .whatsapp import send_whatsapp_message, send_whatsapp_template
from .utils import TEMPLATES, TRIGGER_TEMPLATES

logger = logging.getLogger(__name__)

# Max 10 concurrent WhatsApp HTTP calls at a time
_executor = None
_executor_lock = threading.Lock()

def _get_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=10)
    return _executor


@receiver(post_save, sender="members.MembershipPlan")
def notify_members_on_new_plan(sender, instance, created, **kwargs):
    """
    Fires when a new MembershipPlan is saved for the first time.
    Collects recipients on the main thread then dispatches a single background
    task that sends 1 message every 2 seconds (30/min) to stay within Meta's
    safe rate limits and avoid spam flags.
    Skips if NOTIFY_NEW_PLAN is disabled.
    """
    if not created:
        return
    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled("NOTIFY_NEW_PLAN"):
        return
    from apps.members.models import Member
    from apps.enquiries.models import Enquiry

    template      = TEMPLATES["new_plan"]
    template_name = TRIGGER_TEMPLATES.get("new_plan", "")
    plan_name     = instance.name
    duration      = instance.duration_days
    price         = instance.price

    recipients = []
    for member in Member.objects.filter(status="active").only("name", "phone"):
        recipients.append((member.name, member.phone))
    for enquiry in Enquiry.objects.filter(status__in=("new", "followup")).only("name", "phone"):
        recipients.append((enquiry.name, enquiry.phone))

    def _bulk_send():
        from django.db import connection
        from apps.notifications.utils import bulk_slots_remaining
        connection.close()
        for name, raw_phone in recipients:
            if bulk_slots_remaining() <= 0:
                logger.warning(
                    "new_plan bulk send stopped — BULK_DAILY_CAP reached for today."
                )
                break

            phone = str(raw_phone or "").strip().replace(" ", "").replace("-", "")
            if not phone:
                continue
            if not phone.startswith("91"):
                phone = f"91{phone}"

            body = template.format(name=name, plan_name=plan_name, duration=duration, price=price)
            params = [name, plan_name, str(duration), str(price)]

            notif = Notification.objects.create(
                recipient_name=name,
                recipient_phone=phone,
                channel="whatsapp",
                trigger_type="new_plan",
                message=body,
                template_name=template_name,
                template_params=params,
                status="pending",
            )
            # dispatch_whatsapp_on_create skips new_plan_launch (in _BULK_TEMPLATES)
            # so we send directly here after the 2-second rate-limit sleep.
            result = send_whatsapp_template(
                to=phone,
                template_name=template_name,
                language_code="en",
                body_params=params,
            )
            if result.get("success"):
                Notification.objects.filter(pk=notif.pk).update(
                    status="sent",
                    sent_at=timezone.now(),
                )
                logger.info(f"Bulk new_plan sent to {phone}")
            else:
                Notification.objects.filter(pk=notif.pk).update(
                    status="failed",
                    error_log=result.get("error", "Unknown error"),
                )
                logger.error(f"Bulk new_plan failed for {phone}: {result.get('error')}")

            time.sleep(2)  # 1 message per 2 seconds = 30 per minute

    _get_executor().submit(_bulk_send)


@receiver(post_save, sender="members.MemberAttendance")
def notify_on_member_checkin(sender, instance, created, **kwargs):
    """
    Fires once per real check-in — created=True guards against firing again on
    the check-out update (same row, get_or_create'd earlier that day), and
    `instance.check_in` guards against rows created with no check-in at all
    (e.g. auto-marked-absent). Off by default (NOTIFY_MEMBER_CHECKIN) since this
    is a brand-new, high-frequency notification type — nothing sends until it's
    explicitly turned on in Settings, unlike the pre-existing triggers which
    default on to preserve their prior behavior.
    """
    if not created or not instance.check_in:
        return
    from apps.finances.gst_utils import get_setting, get_admin_whatsapp_number
    if get_setting("NOTIFY_MEMBER_CHECKIN", "false").lower() not in ("true", "1"):
        return
    member = instance.member
    Notification.objects.create(
        recipient_name=member.name,
        recipient_phone=get_admin_whatsapp_number(),
        channel="whatsapp",
        trigger_type="member_checkin",
        message=f"{member.name} checked in at {instance.check_in.strftime('%I:%M %p')}",
        status="pending",
    )
    logger.info(
        f"notify_on_member_checkin: notification queued for member={member.id} "
        f"({member.name}) check_in={instance.check_in}"
    )


@receiver(post_save, sender="staff.StaffAttendance")
def notify_on_staff_checkin(sender, instance, created, **kwargs):
    """Same pattern as notify_on_member_checkin — see that docstring."""
    if not created or not instance.check_in:
        return
    from apps.finances.gst_utils import get_setting, get_admin_whatsapp_number
    if get_setting("NOTIFY_STAFF_CHECKIN", "false").lower() not in ("true", "1"):
        return
    staff = instance.staff
    Notification.objects.create(
        recipient_name=staff.name,
        recipient_phone=get_admin_whatsapp_number(),
        channel="whatsapp",
        trigger_type="staff_checkin",
        message=f"{staff.name} checked in at {instance.check_in.strftime('%I:%M %p')}",
        status="pending",
    )
    logger.info(
        f"notify_on_staff_checkin: notification queued for staff={staff.id} "
        f"({staff.name}) check_in={instance.check_in}"
    )


# Bill templates — require a PDF document header; handled directly by send_bill_on_whatsapp().
_BILL_TEMPLATES = {"membership_bill", "pt_bill"}

# Bulk templates — rate-limited dispatch handled in their own background task;
# the generic signal must skip them to avoid double-sending.
_BULK_TEMPLATES = {"new_plan_launch"}


@receiver(post_save, sender=Notification)
def dispatch_whatsapp_on_create(sender, instance, created, **kwargs):
    """
    Triggers on every new Notification row (status=pending).
    Uses queryset.update() to avoid re-triggering the signal on status update.
    Bill templates and bulk templates are skipped here — they manage their own dispatch.

    Channel routing: GymSetting NOTIFY_CHANNEL_<TRIGGER_TYPE> decides WhatsApp
    (default, unchanged code path below) vs Chrome push (see push.py). This is a
    genuine alternative, not a backup — a failed chrome send does NOT fall back
    to WhatsApp, it just fails and is logged.
    """
    if not created:
        return
    if instance.status != "pending":
        return
    if instance.template_name in _BILL_TEMPLATES:
        return
    if instance.template_name in _BULK_TEMPLATES:
        # Rate-limited dispatch is handled by the bulk sender (_bulk_send above).
        return

    from apps.finances.gst_utils import get_notify_channel
    channel = get_notify_channel(instance.trigger_type)

    if channel == "chrome":
        pk          = instance.pk
        title       = instance.get_trigger_type_display()
        body        = instance.message
        trigger     = instance.trigger_type
        member      = instance.member

        def _send_chrome():
            from django.db import connection
            from .push import send_browser_push_to_all_active, send_browser_push_to_member, MEMBER_ONLY_TRIGGERS
            connection.close()
            if trigger in MEMBER_ONLY_TRIGGERS:
                sent, failed, skip_reason = send_browser_push_to_member(member, title, body)
            else:
                sent, failed = send_browser_push_to_all_active(title, body)
                skip_reason = None
            if sent > 0:
                Notification.objects.filter(pk=pk).update(channel="chrome", status="sent", sent_at=timezone.now())
                logger.info(f"Notification {pk} delivered via chrome push ({sent} sent, {failed} failed)")
            else:
                error_msg = skip_reason or (
                    f"Chrome push delivery failed ({failed} attempt(s) failed, 0 delivered). No WhatsApp fallback by design."
                )
                Notification.objects.filter(pk=pk).update(
                    channel="chrome",
                    status="failed",
                    error_log=error_msg,
                )
                logger.warning(
                    f"Notification {pk} chrome push not delivered — 0 sent, {failed} failed"
                    + (f" (skipped: {skip_reason})" if skip_reason else "")
                )

        _get_executor().submit(_send_chrome)
        return

    if not instance.recipient_phone:
        logger.warning(f"Notification {instance.pk} skipped — no phone number.")
        Notification.objects.filter(pk=instance.pk).update(
            status="failed",
            error_log="No recipient phone number provided.",
        )
        return

    pk            = instance.pk
    phone         = instance.recipient_phone
    message       = instance.message
    template_name = instance.template_name or ""
    template_params = list(instance.template_params or [])
    language_code = instance.language_code or "en"

    def _send():
        # Small delay to avoid hammering Meta API when bulk-creating
        from django.db import connection
        connection.close()
        time.sleep(0.1)
        try:
            if template_name:
                result = send_whatsapp_template(
                    to=phone,
                    template_name=template_name,
                    language_code=language_code,
                    body_params=template_params,
                )
            else:
                result = send_whatsapp_message(to=phone, message=message)

            if result["success"]:
                Notification.objects.filter(pk=pk).update(
                    status="sent",
                    sent_at=timezone.now(),
                )
                logger.info(f"Notification {pk} sent to {phone}")
            else:
                Notification.objects.filter(pk=pk).update(
                    status="failed",
                    error_log=result.get("error", "Unknown error"),
                )
                logger.error(f"Notification {pk} failed: {result.get('error')}")
        except Exception as e:
            logger.exception(f"Notification {pk} thread crashed: {e}")

    _get_executor().submit(_send)
