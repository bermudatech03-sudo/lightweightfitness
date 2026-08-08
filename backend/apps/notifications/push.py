import json
import logging
import threading
import time

from django.conf import settings
from django.utils import timezone
from pywebpush import webpush, WebPushException

from .models import PushSubscription

logger = logging.getLogger(__name__)

# Cross-thread rate gate: at most one push send every _MIN_PUSH_INTERVAL_SECONDS,
# no matter which background thread (or how many concurrent notification events)
# triggered it. Without this, several Notification rows created within
# milliseconds of each other (e.g. a scheduler misfire re-running a job) each
# spawn their own background send, firing a burst of near-identical pushes —
# exactly the pattern Chrome's spam/abuse detection silently suppresses.
_push_rate_lock = threading.Lock()
_last_push_sent_at = 0.0
_MIN_PUSH_INTERVAL_SECONDS = 2.0


def _throttle_push():
    global _last_push_sent_at
    with _push_rate_lock:
        wait = _MIN_PUSH_INTERVAL_SECONDS - (time.monotonic() - _last_push_sent_at)
        if wait > 0:
            logger.info(f"_throttle_push: waiting {wait:.2f}s to keep pushes >= {_MIN_PUSH_INTERVAL_SECONDS}s apart")
            time.sleep(wait)
        _last_push_sent_at = time.monotonic()


def send_browser_push(subscription, title, body, url=None):
    """
    Sends one Web Push notification to a single PushSubscription.

    Returns {"success": True} or {"success": False, "error": "..."} — same shape
    as whatsapp.py's send functions, so callers can handle both channels uniformly.

    Rate-limited to one send every _MIN_PUSH_INTERVAL_SECONDS across the whole
    process (see _throttle_push) — this is the actual serialization point, so it
    applies whether one event fans out to several subscriptions or several
    events fire in a burst from different threads.

    No retry / no fallback to another channel on failure — the caller (signals.py)
    just logs and moves on. A 404/410 response means the browser's subscription is
    gone (expired, revoked, browser data cleared); that's marked inactive here so
    it stops being tried, rather than failing the same way forever.
    """
    _throttle_push()
    payload = json.dumps({"title": title, "body": body, "url": url or "/"})
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
        )
        PushSubscription.objects.filter(pk=subscription.pk).update(last_used_at=timezone.now())
        logger.info(f"send_browser_push: delivered to subscription id={subscription.pk} title={title!r}")
        return {"success": True}
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            PushSubscription.objects.filter(pk=subscription.pk).update(is_active=False)
            logger.warning(
                f"send_browser_push: subscription id={subscription.pk} gone (status={status}), marked inactive"
            )
        else:
            logger.error(
                f"send_browser_push: failed for subscription id={subscription.pk} status={status} error={e}"
            )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"send_browser_push: unexpected error for subscription id={subscription.pk}")
        return {"success": False, "error": str(e)}


# Trigger types that belong to a specific MEMBER, not to admin. signals.py
# checks this to decide which send function to call: send_browser_push_to_member
# (this list) vs send_browser_push_to_all_active (everything else — admin's
# own broadcast). A member-facing trigger here that has no PushSubscription
# yet (member hasn't scanned the admin's QR) simply fails with a clear reason
# — there's still no WhatsApp fallback, by the same design as everywhere else.
MEMBER_ONLY_TRIGGERS = {"absent", "diet_reminder", "renewal_remind", "expiry"}


def send_browser_push_to_all_active(title, body, url=None):
    """
    Broadcasts to every currently-active PushSubscription belonging to a
    superuser. Callers must not use this for MEMBER_ONLY_TRIGGERS — see
    send_browser_push_to_member for those.

    is_superuser (Django's own permission flag) is used rather than the app's
    custom User.role field — role is purely cosmetic today (nothing else in
    the app gates on it, and there's currently no way to create an account
    with role="admin" through the app itself), so it can't be trusted to
    reflect who's actually an admin. is_superuser is the real signal and needs
    no manual upkeep as accounts are created.

    Returns (sent_count, failed_count).
    """
    subscriptions = list(PushSubscription.objects.filter(is_active=True, user__is_superuser=True))
    sent = failed = 0
    for sub in subscriptions:
        result = send_browser_push(sub, title, body, url)
        if result["success"]:
            sent += 1
        else:
            failed += 1
    logger.info(
        f"send_browser_push_to_all_active: title={title!r} -> "
        f"{sent} sent, {failed} failed, {len(subscriptions)} active subscription(s) targeted"
    )
    return sent, failed


def send_browser_push_to_member(member, title, body, url=None):
    """
    Sends to a specific member's active PushSubscription(s) — the Phase 2
    admin-mediated QR link flow (member's browser generates the subscription,
    admin scans it and links it to that member's profile). A member can, in
    principle, have more than one linked device, same as admin/staff.

    Returns (sent_count, failed_count, skip_reason). skip_reason is set (and
    sent/failed both 0) when nothing was actually attempted — either no member
    was linked to the notification at all, or the member has no active
    subscription yet (hasn't gone through the QR opt-in with the admin).
    """
    if member is None:
        return 0, 0, "No member linked to this notification — cannot route it to a specific person."

    subscriptions = list(PushSubscription.objects.filter(is_active=True, member=member))
    if not subscriptions:
        logger.info(f"send_browser_push_to_member: member={member.id} ({member.name}) has no active subscription")
        return 0, 0, f"{member.name} hasn't linked a device for Chrome notifications yet."

    sent = failed = 0
    for sub in subscriptions:
        result = send_browser_push(sub, title, body, url)
        if result["success"]:
            sent += 1
        else:
            failed += 1
    logger.info(
        f"send_browser_push_to_member: member={member.id} ({member.name}) title={title!r} -> "
        f"{sent} sent, {failed} failed, {len(subscriptions)} subscription(s) targeted"
    )
    return sent, failed, None
