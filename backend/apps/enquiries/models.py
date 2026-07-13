from django.db import models
from django.utils import timezone


class Enquiry(models.Model):
    STATUS = [
        ("new",       "New"),
        ("followup",  "Follow-up"),
        ("converted", "Converted"),
        ("lost",      "Lost"),
    ]

    name       = models.CharField(max_length=150)
    phone      = models.CharField(max_length=15)
    email      = models.EmailField(blank=True)
    notes      = models.TextField(blank=True)
    status     = models.CharField(max_length=20, choices=STATUS, default="new", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.phone}) — {self.status}"


class EnquiryFollowup(models.Model):
    """
    One row per scheduled follow-up WhatsApp message for an enquiry.
    Created in bulk (10 rows) when an Enquiry is first saved.
    A daily cron job at 10:00 AM processes rows where scheduled_date = today.
    """
    enquiry        = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="followups")
    scheduled_date = models.DateField()
    sent           = models.BooleanField(default=False)
    sent_at        = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_date"]
        indexes = [models.Index(fields=["scheduled_date", "sent"])]

    def __str__(self):
        return f"Followup for {self.enquiry.name} on {self.scheduled_date}"
