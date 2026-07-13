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
        logger.info("run_auto_mark_absent: starting nightly auto-absent backfill")
        _auto_mark_absent_staff()
        _auto_mark_absent_members()
        logger.info("run_auto_mark_absent: completed")
    except Exception:
        logger.exception("run_auto_mark_absent: failed")

def send_renewal_reminders():
    # Fire exactly 3 days before the renewal date
    target = timezone.now().date() + timedelta(days=3)
    members = list(Member.objects.filter(
        status = "active",
        renewal_date = target,
    ))
    logger.info(f"send_renewal_reminders: found {len(members)} member(s) expiring on {target}")
    for member in members:
        send_notification(member, "renewal_remind")
    logger.info(f"send_renewal_reminders: completed, processed {len(members)} member(s)")

def send_expiry_notices():
    today = timezone.now().date()
    # Auto-expire anyone past renewal date
    auto_expired_count = Member.objects.filter(
        status="active",
        renewal_date__lt=today,
    ).update(status="expired")
    if auto_expired_count:
        logger.info(f"send_expiry_notices: auto-expired {auto_expired_count} member(s) past renewal date")

    # Send expiry notice exactly 3 days after expiry
    target = today - timedelta(days=3)
    members = list(Member.objects.filter(status="expired", renewal_date=target))
    logger.info(f"send_expiry_notices: found {len(members)} member(s) expired on {target}")
    for member in members:
        send_notification(member, "expiry")
    logger.info(f"send_expiry_notices: completed, sent {len(members)} expiry notice(s)")

def send_daily_notice():
    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled("NOTIFY_DAILY_NOTICE"):
        logger.warning("send_daily_notice: skipped — NOTIFY_DAILY_NOTICE is disabled")
        return

    items = list(ToBuy.objects.filter(
        status = "pending",
    ))
    today = timezone.localdate()
    income      = Income.objects.filter(date__year=today.year, date__month=today.month).aggregate(t=Sum("amount"))["t"] or 0
    expenditure = Expenditure.objects.filter(date__year=today.year, date__month=today.month).aggregate(t=Sum("amount"))["t"] or 0
    money_left  = income - expenditure
    logger.info(f"send_daily_notice: found {len(items)} pending item(s) to restock, money_left={money_left}")

    for item in items:
        send_notification_admin(item,money_left,"daily_notice")
    logger.info(f"send_daily_notice: completed, sent {len(items)} notice(s)")

def send_message_for_absentees():
    today = timezone.now().date()
    attended_ids = MemberAttendance.objects.filter(date=today).values_list("member_id", flat=True)
    absentees = list(Member.objects.filter(status="active", personal_trainer=False).exclude(id__in=attended_ids))
    logger.info(f"send_message_for_absentees: found {len(absentees)} absentee(s) for {today}")
    for member in absentees:
        send_notification(member, "absent")
    logger.info(f"send_message_for_absentees: completed, sent {len(absentees)} absent notice(s)")


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

    assignments = list(TrainerAssignment.objects.filter(
        member__status="active",
        member__personal_trainer=True,
    ).select_related("member"))
    logger.info(f"send_message_for_pt_absentees: evaluating {len(assignments)} PT assignment(s) for {today}")

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
    logger.info(f"send_message_for_pt_absentees: completed, notified {len(notified_member_ids)} member(s)")





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

    staff_list = list(StaffMember.objects.filter(status="active").select_related("shift_template"))
    logger.info(f"send_staff_absent_notifications: evaluating {len(staff_list)} active staff member(s) for {today}")

    notified_count = 0
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
        notified_count += 1
    logger.info(f"send_staff_absent_notifications: completed, notified {notified_count} staff member(s)")


def send_diet_notifications():
    from apps.members.models import Diet, Member
    from apps.notifications.models import Notification
    from apps.finances.gst_utils import is_notify_enabled

    if not is_notify_enabled("NOTIFY_DIET_REMINDER"):
        logger.warning("send_diet_notifications: skipped — NOTIFY_DIET_REMINDER is disabled")
        return

    now = timezone.localtime(timezone.now())
    window_start = now.time().replace(second=0, microsecond=0)
    window_end = (now + timedelta(minutes=5)).time().replace(second=0, microsecond=0)

    # Handle window that crosses midnight (e.g. 23:58 → 00:03)
    if window_start <= window_end:
        items = list(Diet.objects.filter(
            time__gte=window_start, time__lt=window_end
        ).select_related("plan"))
    else:
        items = list(Diet.objects.filter(
            Q(time__gte=window_start) | Q(time__lt=window_end)
        ).select_related("plan"))

    logger.info(f"send_diet_notifications: found {len(items)} diet item(s) due in window {window_start}-{window_end}")

    from apps.notifications.utils import TRIGGER_TEMPLATES
    template_name = TRIGGER_TEMPLATES.get("diet_reminder", "")

    sent_count = 0
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
            try:
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
                sent_count += 1
            except Exception:
                logger.exception(f"send_diet_notifications: failed to create notification for {member.name} ({phone})")
    logger.info(f"send_diet_notifications: completed, created {sent_count} notification(s)")


def send_weekly_pending_payment_reminders():
    """
    Runs every Sunday at 10:00 AM.
    - Sends active/paused members with a balance due a reminder to pay.
    - Stops early if BULK_DAILY_CAP is reached (see utils.py to change the limit).
    - Rate-limited to 1 message per 2 seconds (30/min) to stay within Meta's safe limits.
    - Sends admin a summary of all pending-balance members regardless of cap.
    """
    import time
    from django.db.models import Sum, F
    from apps.notifications.utils import (
        send_pending_payment_reminder,
        send_pending_payment_admin_summary,
        bulk_slots_remaining,
    )
    from apps.members.models import Member

    # Filter for a balance at the DB level instead of loading every active/paused
    # member into Python and calling balance_due() (2 aggregate queries each) on
    # all of them just to find the few who actually owe money.
    members_with_balance = list(
        Member.objects.filter(status__in=["active", "paused"])
        .annotate(_ann_total_paid=Sum("payments__amount_paid"), _ann_total_due=Sum("payments__total_with_gst"))
        .filter(_ann_total_due__gt=F("_ann_total_paid"))
    )
    # Pre-seed the memoized total_paid()/total_due() cache (see Member model) from
    # the annotation so send_pending_payment_reminder/_admin_summary below — which
    # call member.balance_due() again to build the message — don't re-query.
    for _m in members_with_balance:
        _m._total_paid_cache = _m._ann_total_paid or 0
        _m._total_due_cache  = _m._ann_total_due or 0

    logger.info(f"send_weekly_pending_payment_reminders: found {len(members_with_balance)} member(s) with a pending balance")

    sent_count = 0
    for member in members_with_balance:
        if bulk_slots_remaining() <= 0:
            logger.warning(
                "Pending payment reminders stopped — BULK_DAILY_CAP reached for today."
            )
            break
        send_pending_payment_reminder(member)
        sent_count += 1
        time.sleep(2)  # 1 message per 2 seconds = 30 per minute

    logger.info(f"send_weekly_pending_payment_reminders: sent {sent_count}/{len(members_with_balance)} member reminder(s)")

    # Admin summary always sends — it is a single message, not subject to the bulk cap.
    if members_with_balance:
        send_pending_payment_admin_summary(members_with_balance)
        logger.info("send_weekly_pending_payment_reminders: admin summary sent")
    else:
        logger.info("send_weekly_pending_payment_reminders: no pending-balance members found, admin summary skipped")


def retry_failed_notifications():
    import time
    from datetime import timedelta
    from apps.notifications.models import Notification
    from apps.notifications.whatsapp import send_whatsapp_message, send_whatsapp_template

    # Templates that must never be retried:
    # - Time-sensitive: message is meaningless after the moment has passed.
    # - Bill templates: originally sent with a PDF document header that cannot
    #   be reconstructed here; Meta would reject the call without it.
    _NO_RETRY_TEMPLATES = {
        "absent_reminder",    # tied to a specific date — stale after a few hours
        "diet_reminder",      # tied to a specific meal time — stale immediately
        "membership_bill",    # requires PDF document header
        "pt_bill",            # requires PDF document header
    }

    MAX_RETRIES = 3
    BATCH_SIZE  = 50
    cutoff      = timezone.now() - timedelta(hours=24)  # only retry last 24 hrs

    failed = list(Notification.objects.filter(
        status="failed",
        retry_count__lt=MAX_RETRIES,
        created_at__gte=cutoff,
    ).exclude(
        template_name__in=_NO_RETRY_TEMPLATES,
    )[:BATCH_SIZE])

    logger.info(f"retry_failed_notifications: found {len(failed)} failed notification(s) eligible for retry")

    attempted_count = 0
    succeeded_count = 0
    for notif in failed:
        if not notif.recipient_phone:
            logger.warning(f"retry_failed_notifications: notification {notif.pk} has no recipient phone, skipping")
            continue
        attempted_count += 1
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
            succeeded_count += 1
            logger.info(f"retry_failed_notifications: notification {notif.pk} retried successfully")
        else:
            Notification.objects.filter(pk=notif.pk).update(
                retry_count=notif.retry_count + 1,
                error_log=result.get("error", "Unknown error"),
            )
            logger.warning(f"retry_failed_notifications: notification {notif.pk} retry failed: {result.get('error')}")
        time.sleep(0.1)   # 100ms between retries

    logger.info(f"retry_failed_notifications: completed, attempted {attempted_count}, succeeded {succeeded_count}")


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

    due = list(EnquiryFollowup.objects.filter(
        scheduled_date=today, sent=False
    ).select_related("enquiry"))
    logger.info(f"send_enquiry_followups: found {len(due)} follow-up(s) due for {today}")

    sent_count = 0
    skipped_status_count = 0
    notify_disabled_logged = False
    for followup in due:
        enquiry = followup.enquiry
        if enquiry.status != "followup":
            followup.sent = True
            followup.sent_at = timezone.now()
            followup.save()
            skipped_status_count += 1
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
            sent_count += 1
        elif not notify_disabled_logged:
            logger.warning("send_enquiry_followups: NOTIFY_ENQUIRY_FOLLOWUP is disabled — due follow-ups will be marked sent without messaging")
            notify_disabled_logged = True

        followup.sent    = True
        followup.sent_at = timezone.now()
        followup.save()

    lost_count = Enquiry.objects.filter(
        status__in=["new", "followup"]
    ).annotate(
        last_followup=Max("followups__scheduled_date")
    ).filter(
        last_followup__lt=today
    ).update(status="lost")

    logger.info(
        f"send_enquiry_followups: completed, sent {sent_count}, skipped {skipped_status_count} "
        f"(status not 'followup'), marked {lost_count} enquiry(ies) as lost"
    )


