import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)


def get_setting(key, default=""):
    """Read a GymSetting value from the DB. Falls back to default if not found."""
    try:
        from apps.finances.models import GymSetting
        obj = GymSetting.objects.filter(key=key).first()
        if obj is None:
            logger.warning(f"GymSetting '{key}' not found in DB, using default={default}")
            return default
        return obj.value
    except Exception:
        logger.error(f"get_setting: error reading GymSetting '{key}' from DB, falling back to default={default}", exc_info=True)
        return default


def is_notify_enabled(setting_key):
    """Return True if the WhatsApp notification toggle is on (default: True)."""
    return get_setting(setting_key, "true").lower() not in ("false", "0", "no")


def get_gst_rate():
    rate = Decimal(get_setting("GST_RATE", "18"))
    logger.info(f"get_gst_rate: GST_RATE={rate}%")
    return rate


def get_pt_payable_percent():
    percent = Decimal(get_setting("PT_PAYABLE_PERCENT", "100"))
    logger.info(f"get_pt_payable_percent: PT_PAYABLE_PERCENT={percent}%")
    return percent


def get_diet_plan_amount():
    amount = Decimal(get_setting("DIET_PLAN_AMOUNT", "0"))
    logger.info(f"get_diet_plan_amount: DIET_PLAN_AMOUNT={amount}")
    return amount


def calc_gst(base_price):
    """
    Given a base amount (excluding GST), return (base, gst_amount, total, rate).
    If GST_RATE is 0, all amounts equal base.
    """
    base    = Decimal(str(base_price))
    rate    = get_gst_rate()
    gst_amt = (base * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    total   = base + gst_amt
    logger.info(f"calc_gst: base={base} rate={rate}% -> gst_amount={gst_amt} total={total}")
    return base, gst_amt, total, float(rate)


def calc_gst_from_total(total_amount):
    """
    Given a total (GST-inclusive), back-calculate base and GST.
    """
    total = Decimal(str(total_amount))
    rate  = get_gst_rate()
    if rate == 0:
        logger.info(f"calc_gst_from_total: total={total} rate=0% -> base={total} gst_amount=0.00")
        return total, Decimal("0"), total, float(rate)
    base    = (total / (1 + rate / 100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    gst_amt = total - base
    logger.info(f"calc_gst_from_total: total={total} rate={rate}% -> base={base} gst_amount={gst_amt}")
    return base, gst_amt, total, float(rate)


def get_admin_whatsapp_number():
    """
    Returns the admin WhatsApp number from GymSetting (DB).
    Falls back to the env/settings value so nothing breaks if the DB row is empty.
    """
    from django.conf import settings as _s
    db_val = get_setting("ADMIN_WHATSAPP_NUMBER", "")
    if db_val:
        return db_val
    logger.warning("ADMIN_WHATSAPP_NUMBER not set in GymSetting DB, falling back to settings/env value")
    return getattr(_s, "ADMIN_WHATSAPP_NUMBER", "")


def get_gym_info():
    """Return gym details from GymSetting DB table."""
    return {
        "name":    get_setting("GYM_NAME",    "Gym"),
        "address": get_setting("GYM_ADDRESS", ""),
        "phone":   get_setting("GYM_PHONE",   ""),
        "email":   get_setting("GYM_EMAIL",   ""),
        "gstin":   get_setting("GYM_GSTIN",   ""),
    }


def make_invoice_number(member_id, date):
    return f"INV-{date.year}{date.month:02d}-M{member_id:04d}"
