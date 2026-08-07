import json
import logging

from django.conf import settings
from django.utils import timezone
from pywebpush import webpush, WebPushException

from .models import PushSubscription

logger = logging.getLogger(__name__)


def send_browser_push(subscription, title, body, url=None):
    """
    Sends one Web Push notification to a single PushSubscription.

    Returns {"success": True} or {"success": False, "error": "..."} — same shape
    as whatsapp.py's send functions, so callers can handle both channels uniformly.

    No retry / no fallback to another channel on failure — the caller (signals.py)
    just logs and moves on. A 404/410 response means the browser's subscription is
    gone (expired, revoked, browser data cleared); that's marked inactive here so
    it stops being tried, rather than failing the same way forever.
    """
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


def send_browser_push_to_all_active(title, body, url=None):
    """
    Broadcasts to every currently-active PushSubscription (Phase 1: this is
    admin/staff devices, plus the kiosk once it's subscribed — there's no
    per-member targeting yet, see PushSubscription.user).
    Returns (sent_count, failed_count).
    """
    subscriptions = list(PushSubscription.objects.filter(is_active=True))
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
