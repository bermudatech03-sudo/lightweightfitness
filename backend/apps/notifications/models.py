from django.conf import settings
from django.db import models


class PushSubscription(models.Model):
    """
    One row per browser+device that has enabled Chrome/browser push notifications.
    Admin/staff subscriptions are linked to their account (`user`). Member-linked
    subscriptions are a Phase 2 addition — `user` stays null for those until the
    member-facing opt-in flow exists.
    """
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="push_subscriptions", null=True, blank=True)
    endpoint     = models.TextField(unique=True)
    p256dh       = models.CharField(max_length=255)
    auth         = models.CharField(max_length=255)
    user_agent   = models.CharField(max_length=255, blank=True)
    is_active    = models.BooleanField(default=True, db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.user.username if self.user_id else "unlinked"
        return f"PushSubscription({who}, active={self.is_active})"


class Notification(models.Model):
    CHANNEL = [("whatsapp", "WhatsApp"), ("chrome", "Chrome Push")]
    STATUS  = [("sent", "Sent"), ("failed", "Failed"), ("pending", "Pending")]
    TRIGGER = [
        ("renewal_remind",         "Renewal Reminder"),
        ("renewal_confirm",        "Renewal Confirmed"),
        ("enrollment",             "New Enrollment"),
        ("expiry",                 "Membership Expired"),
        ("manual",                 "Manual"),
        ("enquiry_welcome",        "Enquiry Welcome"),
        ("enquiry_followup",       "Enquiry Follow-up"),
        ("absent",                 "Member Absent"),
        ("staff_absent",           "Staff Absent"),
        ("member_checkin",         "Member Check-in"),
        ("staff_checkin",          "Staff Check-in"),
        ("new_plan",               "New Plan Announcement"),
        ("diet_reminder",          "Diet Reminder"),
        ("pending_payment_member", "Pending Payment Reminder"),
        ("pending_payment_admin",  "Pending Payment Summary (Admin)"),
        # Bill-send events
        ("balance",                "Balance Payment Bill"),
        ("pt_renewal",             "PT Renewal Bill"),
        ("pt_balance",             "PT Balance Payment Bill"),
    ]

    recipient_name  = models.CharField(max_length=150)
    recipient_phone = models.CharField(max_length=20, blank=True)
    channel         = models.CharField(max_length=10, choices=CHANNEL, default="whatsapp")
    trigger_type    = models.CharField(max_length=30, choices=TRIGGER, default="manual", db_index=True)
    message         = models.TextField()
    template_name   = models.CharField(max_length=100, blank=True, default="")
    template_params = models.JSONField(default=list, blank=True)
    language_code   = models.CharField(max_length=10, blank=True, default="en")
    status          = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    sent_at         = models.DateTimeField(null=True, blank=True)
    error_log       = models.TextField(blank=True)
    retry_count     = models.PositiveSmallIntegerField(default=0)
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.trigger_type} → {self.recipient_name} [{self.status}]"