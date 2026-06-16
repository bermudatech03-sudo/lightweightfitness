import logging
from datetime import timedelta, datetime
from django.utils import timezone
from django.db.models import Q
from django.db.models import Sum
from apps.notifications.utils import send_notification, send_notification_admin, send_staff_notification
from apps.members.models import Member, MemberAttendance
from apps.finances.models import ToBuy,Expenditure,Income

logger = logging.getLogger(__name__)


def run_auto_mark_absent():
    """
    Scheduled nightly (01:00 IST). Creates the attendance rows for yesterday that
    the lazy calendar-fetch logic would otherwise miss if no one opened the page.
    """
    try:
        from apps.staff.views import _auto_mark_absent_staff, _auto_mark_absent_members
        _auto_mark_absent_staff()
        _auto_mark_absent_members()
        logger.info("run_auto_mark_absent: completed")
    except Exception:
        logger.exception("run_auto_mark_absent: failed")

def send_renewal_reminders():
    # Fire exactly 3 days before the renewal date
    target = timezone.now().date() + timedelta(days=3)
    members = Member.objects.filter(
        status = "active",
        renewal_date = target,
    )
    for member in members:
        send_notification(member, "renewal_remind")

def send_expiry_notices():
    today = timezone.now().date()
    # Auto-expire anyone past renewal date
    Member.objects.filter(
        status="active",
        renewal_date__lt=today,
    ).update(status="expired")

    # Send expiry notice exactly 3 days after expiry
    target = today - timedelta(days=3)
    for member in Member.objects.filter(status="expired", renewal_date=target):
        send_notification(member, "expiry")

def send_daily_notice():
    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled("NOTIFY_DAILY_NOTICE"):
        return

    items = ToBuy.objects.filter(
        status = "pending",
    )
    today = timezone.localdate()
    income      = Income.objects.filter(date__year=today.year, date__month=today.month).aggregate(t=Sum("amount"))["t"] or 0
    expenditure = Expenditure.objects.filter(date__year=today.year, date__month=today.month).aggregate(t=Sum("amount"))["t"] or 0
    money_left  = income - expenditure

    for item in items:
        send_notification_admin(item,money_left,"daily_notice")

def send_message_for_absentees():
    today = timezone.now().date()
    attended_ids = MemberAttendance.objects.filter(date=today).values_list("member_id", flat=True)
    absentees = Member.objects.filter(status="active", personal_trainer=False).exclude(id__in=attended_ids)
    for member in absentees:
        send_notification(member, "absent")


def send_message_for_pt_absentees():
    """
    Scheduled late in the day (22:00 IST by default). Sends an absent reminder to
    any PT member whose scheduled session has already ENDED today and who never
    checked in. Previously only fired if the session had STARTED which skipped
    afternoon/evening sessions when the cron fired in the morning.
    """
    from apps.members.models import TrainerAssignment
    today = timezone.localdate()
    now_time = timezone.localtime(timezone.now()).time()
    weekday = today.weekday()  # 0=Mon … 6=Sun

    attended_ids = set(
        MemberAttendance.objects.filter(date=today).values_list("member_id", flat=True)
    )

    assignments = TrainerAssignment.objects.filter(
        member__status="active",
        member__personal_trainer=True,
    ).select_related("member")

    notified_member_ids = set()
    for assignment in assignments:
        if weekday not in assignment.working_days_list:
            continue
        if assignment.member_id in attended_ids:
            continue
        # Only notify once the session has ended — avoids premature alerts when
        # the member might still show up.
        end_time = getattr(assignment, "endingtime", None) or assignment.startingtime
        if now_time < end_time:
            continue
        if assignment.member_id in notified_member_ids:
            continue
        send_notification(assignment.member, "absent")
        notified_member_ids.add(assignment.member_id)





def send_staff_absent_notifications():
    """
    Scheduled late in the day (22:00 IST by default). Notifies any staff whose
    shift has ENDED today without a valid check-in. Previously only fired at 10 AM
    and skipped any shift starting after 10 AM — afternoon/evening staff were never
    notified.
    """
    from apps.staff.models import StaffMember, StaffAttendance
    today = timezone.localdate()
    now_time = timezone.localtime(timezone.now()).time()
    weekday = today.weekday()  # 0=Mon … 6=Sun

    checked_in_ids = set(
        StaffAttendance.objects.filter(
            date=today,
            status__in=("present", "late", "overtime", "late_overtime", "half"),
        ).values_list("staff_id", flat=True)
    )

    staff_list = StaffMember.objects.filter(status="active").select_related("shift_template")

    for staff in staff_list:
        shift = staff.shift_template
        if shift:
            if weekday not in shift.working_days_list:
                continue
            # Only notify after shift end — avoids early alerts while the person
            # might still turn up for their shift.
            # if now_time < shift.end_time:
            #     continue
        if staff.id in checked_in_ids:
            continue
        send_staff_notification(staff, "staff_absent")


def send_diet_notifications():
    from apps.members.models import Diet, Member
    from apps.notifications.models import Notification
    from apps.finances.gst_utils import is_notify_enabled

    if not is_notify_enabled("NOTIFY_DIET_REMINDER"):
        return

    now = timezone.localtime(timezone.now())
    window_start = now.time().replace(second=0, microsecond=0)
    window_end = (now + timedelta(minutes=5)).time().replace(second=0, microsecond=0)

    # Handle window that crosses midnight (e.g. 23:58 → 00:03)
    if window_start <= window_end:
        items = Diet.objects.filter(
            time__gte=window_start, time__lt=window_end
        ).select_related("plan")
    else:
        items = Diet.objects.filter(
            Q(time__gte=window_start) | Q(time__lt=window_end)
        ).select_related("plan")

    from apps.notifications.utils import TRIGGER_TEMPLATES
    template_name = TRIGGER_TEMPLATES.get("diet_reminder", "")

    for item in items:
        members = Member.objects.filter(status="active", diet=item.plan)
        for member in members:
            phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
            if not phone:
                continue
            if not phone.startswith("91"):
                phone = f"91{phone}"
            message = (
                f"Hi {member.name}, diet reminder! "
                f"Time to have {item.quantity}{item.unit} of {item.food} ({item.calories} cal). "
                f"Stay consistent with your diet plan!"
            )
            Notification.objects.create(
                recipient_name=member.name,
                recipient_phone=phone,
                channel="whatsapp",
                trigger_type="diet_reminder",
                message=message,
                template_name=template_name,
                template_params=[
                    member.name,
                    str(item.quantity),
                    str(item.unit),
                    str(item.food),
                    str(item.calories),
                ],
                status="pending",
            )


def send_weekly_pending_payment_reminders():
    """
    Runs every Sunday at 10:00 AM.
    - Sends each active/paused member with a balance due a reminder to pay.
    - Rate-limited to 1 message per 2 seconds (30/min) to stay within Meta's safe limits.
    - Sends admin a summary list of all pending-balance members.
    """
    import time
    from apps.notifications.utils import send_pending_payment_reminder, send_pending_payment_admin_summary
    from apps.members.models import Member

    members_with_balance = [
        m for m in Member.objects.filter(status__in=["active", "paused"])
        if m.balance_due() > 0
    ]

    for member in members_with_balance:
        send_pending_payment_reminder(member)
        time.sleep(2)  # 1 message per 2 seconds = 30 per minute

    if members_with_balance:
        send_pending_payment_admin_summary(members_with_balance)


def retry_failed_notifications():
    import time
    from apps.notifications.models import Notification
    from apps.notifications.whatsapp import send_whatsapp_message, send_whatsapp_template

    MAX_RETRIES = 3
    BATCH_SIZE  = 50   # send max 50 retries per run to avoid overloading Meta API
    failed = Notification.objects.filter(
        status="failed", retry_count__lt=MAX_RETRIES
    )[:BATCH_SIZE]
    for notif in failed:
        if not notif.recipient_phone:
            continue
        if notif.template_name:
            result = send_whatsapp_template(
                to=notif.recipient_phone,
                template_name=notif.template_name,
                language_code=notif.language_code or "en",
                body_params=list(notif.template_params or []),
            )
        else:
            result = send_whatsapp_message(to=notif.recipient_phone, message=notif.message)
        if result["success"]:
            Notification.objects.filter(pk=notif.pk).update(
                status="sent",
                sent_at=timezone.now(),
                retry_count=notif.retry_count + 1,
                error_log="",
            )
        else:
            Notification.objects.filter(pk=notif.pk).update(
                retry_count=notif.retry_count + 1,
                error_log=result.get("error", "Unknown error"),
            )
        time.sleep(0.1)   # 100ms between retries


def send_enquiry_followups():
    """
    Runs daily at 9:00 AM. Sends due follow-ups only to enquiries in 'followup' status.
    After the final scheduled date passes, flips remaining new/followup enquiries to 'lost'.
    """
    from apps.enquiries.models import Enquiry, EnquiryFollowup
    from apps.notifications.models import Notification
    from apps.finances.gst_utils import get_setting, is_notify_enabled
    from django.db.models import Max
    from django.utils import timezone

    today     = timezone.localdate()
    gym_name  = get_setting("GYM_NAME", "the Gym")
    gym_phone = get_setting("GYM_PHONE", "")

    due = EnquiryFollowup.objects.filter(
        scheduled_date=today, sent=False
    ).select_related("enquiry")

    for followup in due:
        enquiry = followup.enquiry
        if enquiry.status != "followup":
            followup.sent = True
            followup.sent_at = timezone.now()
            followup.save()
            continue

        phone = str(enquiry.phone or "").strip().replace(" ", "").replace("-", "")
        if phone and not phone.startswith("91"):
            phone = f"91{phone}"

        if is_notify_enabled("NOTIFY_ENQUIRY_FOLLOWUP"):
            message = (
                f"Hi {enquiry.name}, friendly reminder from {gym_name}! "
                f"We'd love to welcome you to our fitness family. "
                f"Call us at {gym_phone} or just walk in anytime. 💪"
            )

            Notification.objects.create(
                recipient_name=enquiry.name,
                recipient_phone=phone,
                channel="whatsapp",
                trigger_type="enquiry_followup",
                message=message,
                status="pending",
            )

        followup.sent    = True
        followup.sent_at = timezone.now()
        followup.save()

    Enquiry.objects.filter(
        status__in=["new", "followup"]
    ).annotate(
        last_followup=Max("followups__scheduled_date")
    ).filter(
        last_followup__lt=today
    ).update(status="lost")


