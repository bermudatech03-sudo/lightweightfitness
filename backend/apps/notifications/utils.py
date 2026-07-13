import logging
from django.utils import timezone

from apps.finances.gst_utils import get_admin_whatsapp_number
from .models import Notification

logger = logging.getLogger(__name__)

# ── Bulk-send daily cap ────────────────────────────────────────────────────────
# Meta Tier 1 (post Business Verification): ~2,000 unique recipients / 24 hrs.
# Capped at 1,500 to leave headroom for transactional messages.
# Developer increases this value as the Meta account tier is upgraded.
#   Tier 1  → 1_500   (current)
#   Tier 2  → 8_000
#   Tier 3  → 80_000
BULK_DAILY_CAP = 1_500

_BULK_TEMPLATE_NAMES = frozenset({"new_plan_launch", "pending_payment_reminder"})


def bulk_slots_remaining() -> int:
    """Return how many more bulk messages can be sent today under BULK_DAILY_CAP."""
    from django.utils import timezone
    sent_today = Notification.objects.filter(
        created_at__date=timezone.localdate(),
        template_name__in=_BULK_TEMPLATE_NAMES,
        status__in=("sent", "pending"),
    ).count()
    return max(0, BULK_DAILY_CAP - sent_today)


# Free-form rendered-text fallback (stored on Notification.message for display/history).
# The actual delivery goes through Meta-approved WhatsApp templates — see TRIGGER_TEMPLATES.
TEMPLATES = {
    "renewal_remind":       "Hi {name}, your gym membership expires on {date}. Renew now to keep your fitness streak going!",
    "renewal_confirm":      "Hi {name}, your membership has been renewed and is valid until {date}. Keep crushing it!",
    "enrollment":           "Hi {name}, welcome aboard! Your membership starts today and is valid until {date}. See you at the gym!",
    "expiry":               "Hi {name}, your gym membership expired on {date}. Renew now to regain access. We miss you!",
    "manual":               "Hi {name}, you have a notification from the gym.",
    "absent":               "Hi {name}, you did not check in at the gym on {date}. Please try to stay consistent to maintain a healthy routine.",
    "daily_notice":         "Hi Admin, you need to restock {itemName}. Current balance: Rs.{moneyLeft}. Please purchase {itemName} by {date}.",
    "staff_absent_self":    "Hi {name}, you have not checked in for your shift on {date}. Please contact the gym management if you need to apply for leave.",
    "staff_absent_admin":   "Hi Admin, {staff_name} ({role}) has not checked in for their shift on {date}. Please follow up.",
    "new_plan":             "Hi {name}, we just launched a new membership plan - {plan_name} for {duration} days at Rs.{price}. Visit us or call to enroll today!",
    "diet_reminder":        "Hi {name}, diet reminder! Time to have {quantity}{unit} of {food} ({calories} cal). Stay consistent with your diet plan!",
    "pending_payment_member": "Hi {name}, you have a pending balance of Rs.{balance} for your gym membership. Please clear the payment at the earliest to ensure uninterrupted access.",
    "pending_payment_admin":  "Hi Admin, {count} member(s) have a pending balance totalling Rs.{total}. Details:\n{details}",
}


# trigger_type → approved Meta template name.
# Keep names in sync with WhatsApp Manager → Message templates.
TRIGGER_TEMPLATES = {
    "renewal_remind":   "renewal_remind",
    "renewal_confirm":  "renewal_confirm",
    "enrollment":       "enrollment_welcome",
    "expiry":           "membership_expiry",
    "absent":           "absent_reminder",
    "new_plan":         "new_plan_launch",
    "diet_reminder":    "diet_reminder",
    "daily_notice":     "stock_alert_admin",
    "staff_absent_self":       "staff_absent_self",
    "staff_absent_admin":      "staff_absent_admin",
    "pending_payment_member":  "pending_payment_reminder",
    "pending_payment_admin":   "pending_payment_admin_summary",
}


_TRIGGER_SETTING_KEY = {
    "enrollment":             "NOTIFY_ENROLLMENT",
    "renewal_confirm":        "NOTIFY_RENEWAL_CONFIRM",
    "renewal_remind":         "NOTIFY_RENEWAL_REMIND",
    "expiry":                 "NOTIFY_EXPIRY",
    "absent":                 "NOTIFY_ABSENT",
    "pending_payment_member": "NOTIFY_PENDING_PAYMENT_MEMBER",
    "pending_payment_admin":  "NOTIFY_PENDING_PAYMENT_ADMIN",
}


def _normalize_phone(raw: str) -> str:
    phone = str(raw or "").strip().replace(" ", "").replace("-", "")
    if phone and not phone.startswith("91"):
        phone = f"91{phone}"
    return phone


def send_notification(member, trigger_type: str):
    """
    Builds the message + template-parameter payload and inserts a Notification row with
    status='pending'. The post_save signal in signals.py routes delivery through the
    approved WhatsApp template (see TRIGGER_TEMPLATES).
    Skips silently if the corresponding WhatsApp notification toggle is disabled,
    or if the individual member has notifications turned off.
    """
    if not getattr(member, "notifications_enabled", True):
        logger.warning(f"send_notification: skipped — notifications disabled for member {member.name!r} (trigger={trigger_type})")
        return

    from apps.finances.gst_utils import is_notify_enabled
    setting_key = _TRIGGER_SETTING_KEY.get(trigger_type)
    if setting_key and not is_notify_enabled(setting_key):
        logger.warning(f"send_notification: skipped — {setting_key} is disabled (trigger={trigger_type}, member={member.name!r})")
        return

    template = TEMPLATES.get(trigger_type, "Hi {name}.")
    date = str(timezone.now().date()) if trigger_type == "absent" else str(member.renewal_date or "")
    body = template.format(name=member.name, date=date)
    phone = _normalize_phone(member.phone)

    # Template params — ORDER MUST MATCH the approved template body ({{1}}, {{2}}, ...)
    template_name = TRIGGER_TEMPLATES.get(trigger_type, "")
    template_params: list = []
    if trigger_type in ("renewal_remind", "renewal_confirm", "enrollment", "expiry", "absent"):
        template_params = [member.name, date]

    logger.info(f"send_notification: creating notification for {member.name!r} ({phone}), trigger={trigger_type}")
    try:
        Notification.objects.create(
            recipient_name=member.name,
            recipient_phone=phone,
            channel="whatsapp",
            trigger_type=trigger_type,
            message=body,
            template_name=template_name,
            template_params=template_params,
            status="pending",
        )
    except Exception:
        logger.exception(f"send_notification: failed to create notification for {member.name!r} (trigger={trigger_type})")
        raise


def send_staff_notification(staff, trigger_type: str):
    """
    Sends a WhatsApp notification to a staff member and to the admin
    about the staff member's absence. Skips silently if NOTIFY_STAFF_ABSENT is disabled.
    """
    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled("NOTIFY_STAFF_ABSENT"):
        logger.warning(f"send_staff_notification: skipped — NOTIFY_STAFF_ABSENT is disabled (staff={staff.name!r})")
        return

    today = str(timezone.now().date())

    logger.info(f"send_staff_notification: creating self + admin notifications for staff {staff.name!r}, trigger={trigger_type}")

    # Staff self
    body_self = TEMPLATES["staff_absent_self"].format(name=staff.name, date=today)
    try:
        Notification.objects.create(
            recipient_name=staff.name,
            recipient_phone=_normalize_phone(staff.phone),
            channel="whatsapp",
            trigger_type=trigger_type,
            message=body_self,
            template_name=TRIGGER_TEMPLATES["staff_absent_self"],
            template_params=[staff.name, today],
            status="pending",
        )
    except Exception:
        logger.exception(f"send_staff_notification: failed to create self notification for staff {staff.name!r}")
        raise

    # Admin
    role = staff.get_role_display()
    body_admin = TEMPLATES["staff_absent_admin"].format(
        staff_name=staff.name, role=role, date=today,
    )
    try:
        Notification.objects.create(
            recipient_name="Admin",
            recipient_phone=_normalize_phone(get_admin_whatsapp_number()),
            channel="whatsapp",
            trigger_type=trigger_type,
            message=body_admin,
            template_name=TRIGGER_TEMPLATES["staff_absent_admin"],
            template_params=[staff.name, role, today],
            status="pending",
        )
    except Exception:
        logger.exception(f"send_staff_notification: failed to create admin notification for staff {staff.name!r}")
        raise


def send_notification_admin(item, moneyleft, trigger_type: str):
    template = TEMPLATES.get(trigger_type, "Hi {name}.")
    date_str = str(item.BuyingDate or "")
    body = template.format(itemName=item.item_name, moneyLeft=moneyleft, date=date_str)

    logger.info(f"send_notification_admin: creating notification for item {item.item_name!r}, trigger={trigger_type}")
    try:
        Notification.objects.create(
            recipient_name=item.item_name,
            recipient_phone=_normalize_phone(get_admin_whatsapp_number()),
            channel="whatsapp",
            trigger_type=trigger_type,
            message=body,
            template_name=TRIGGER_TEMPLATES.get(trigger_type, ""),
            template_params=[item.item_name, str(moneyleft), date_str],
            status="pending",
        )
    except Exception:
        logger.exception(f"send_notification_admin: failed to create notification for item {item.item_name!r}")
        raise


def send_pending_payment_reminder(member):
    """
    Sends a weekly pending balance reminder to a single member.
    Skips silently if NOTIFY_PENDING_PAYMENT_MEMBER toggle is off,
    or if the individual member has notifications turned off.
    """
    if not getattr(member, "notifications_enabled", True):
        logger.warning(f"send_pending_payment_reminder: skipped — notifications disabled for member {member.name!r}")
        return

    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled(_TRIGGER_SETTING_KEY["pending_payment_member"]):
        logger.warning(f"send_pending_payment_reminder: skipped — NOTIFY_PENDING_PAYMENT_MEMBER is disabled (member={member.name!r})")
        return

    balance = f"{member.balance_due():.2f}"
    body    = TEMPLATES["pending_payment_member"].format(name=member.name, balance=balance)

    logger.info(f"send_pending_payment_reminder: creating notification for {member.name!r}, balance=Rs.{balance}")
    try:
        Notification.objects.create(
            recipient_name  = member.name,
            recipient_phone = _normalize_phone(member.phone),
            channel         = "whatsapp",
            trigger_type    = "pending_payment_member",
            message         = body,
            template_name   = TRIGGER_TEMPLATES["pending_payment_member"],
            template_params = [member.name, balance],
            status          = "pending",
        )
    except Exception:
        logger.exception(f"send_pending_payment_reminder: failed to create notification for {member.name!r}")
        raise


def send_pending_payment_admin_summary(members_with_balance):
    """
    Sends weekly pending balance summary to admin.
    Skips silently if NOTIFY_PENDING_PAYMENT_ADMIN toggle is off or admin number not set.
    """
    from apps.finances.gst_utils import is_notify_enabled
    if not is_notify_enabled(_TRIGGER_SETTING_KEY["pending_payment_admin"]):
        return

    admin_phone = _normalize_phone(get_admin_whatsapp_number())
    if not admin_phone:
        logger.warning("send_pending_payment_admin_summary: ADMIN_WHATSAPP_NUMBER not set — skipped")
        return

    count   = len(members_with_balance)
    total   = f"{sum(m.balance_due() for m in members_with_balance):.2f}"
    lines   = [f"- {m.name} ({m.phone}): Rs.{m.balance_due():.2f}" for m in members_with_balance[:30]]
    if count > 30:
        lines.append(f"...and {count - 30} more.")
    details = "\n".join(lines)
    body    = TEMPLATES["pending_payment_admin"].format(count=count, total=total, details=details)

    logger.info(f"send_pending_payment_admin_summary: creating admin summary notification for {count} member(s), total=Rs.{total}")
    try:
        Notification.objects.create(
            recipient_name  = "Admin",
            recipient_phone = admin_phone,
            channel         = "whatsapp",
            trigger_type    = "pending_payment_admin",
            message         = body,
            template_name   = TRIGGER_TEMPLATES["pending_payment_admin"],
            template_params = [str(count), total],
            status          = "pending",
        )
    except Exception:
        logger.exception("send_pending_payment_admin_summary: failed to create admin summary notification")
        raise
