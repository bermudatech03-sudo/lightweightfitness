from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta
import datetime as dt
import logging

logger = logging.getLogger(__name__)


# ─── Day-of-week choices (0=Mon … 6=Sun) ────────────────────────────────────
PRESET_WEEK_CHOICES = [
    ("mon_sun", "Mon – Sun (All week)"),
    ("mon_fri", "Mon – Fri (Weekdays)"),
    ("mon_sat", "Mon – Sat"),
    ("sat_sun", "Sat – Sun (Weekends)"),
    ("custom",  "Custom days"),
]


class StaffShift(models.Model):
    """
    Reusable shift template assigned to staff members.

    working_days  — comma-separated integers "0,1,2,3,4" (Mon=0 … Sun=6)
                    auto-populated from working_days_preset unless "custom".
    start_time / end_time — clock boundaries of the shift.

    Examples
    --------
    Morning Weekday  :  Mon-Fri   06:00 – 14:00
    Evening All-week :  Mon-Sun   14:00 – 22:00
    Weekend PT       :  Sat-Sun   07:00 – 15:00
    """
    name                       = models.CharField(max_length=100, unique=True)
    working_days_preset        = models.CharField(
        max_length=10, choices=PRESET_WEEK_CHOICES, default="mon_sun"
    )
    # "0,1,2,3,4,5,6" — use .working_days_list property
    working_days               = models.CharField(max_length=20, default="0,1,2,3,4,5,6")
    start_time                 = models.TimeField()
    end_time                   = models.TimeField()
    # Minutes after start_time before a check-in counts as "late"
    late_grace_minutes         = models.PositiveIntegerField(default=15)
    # Minutes beyond end_time before check-out counts as "overtime"
    overtime_threshold_minutes = models.PositiveIntegerField(default=30)
    notes                      = models.TextField(blank=True)
    created_at                 = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')})"

    # ── Helpers ──────────────────────────────────────────────────────────────

    @property
    def working_days_list(self):
        """Returns list of ints e.g. [0,1,2,3,4]"""
        if not self.working_days:
            return list(range(7))
        return [int(d) for d in self.working_days.split(",") if d.strip().isdigit()]

    @property
    def working_day_names(self):
        day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        return [day_map[d] for d in self.working_days_list]

    def shift_duration_minutes(self):
        base  = dt.date.today()
        start = datetime.combine(base, self.start_time)
        end   = datetime.combine(base, self.end_time)
        if end < start:          # overnight shift
            end += timedelta(days=1)
        return int((end - start).total_seconds() / 60)

    def is_working_day(self, date):
        return date.weekday() in self.working_days_list

    def save(self, *args, **kwargs):
        preset_map = {
            "mon_sun": "0,1,2,3,4,5,6",
            "mon_fri": "0,1,2,3,4",
            "mon_sat": "0,1,2,3,4,5",
            "sat_sun": "5,6",
        }
        if self.working_days_preset in preset_map:
            self.working_days = preset_map[self.working_days_preset]
        super().save(*args, **kwargs)


class StaffMember(models.Model):
    SHIFT  = [("morning", "Morning 6AM-2PM"), ("evening", "Evening 2PM-10PM"),
              ("full", "Full Day"), ("off", "Day Off")]
    ROLE   = [("trainer", "Trainer"), ("receptionist", "Receptionist"),
              ("cleaner", "Cleaner"), ("manager", "Manager"), ("other", "Other")]
    STATUS = [("active", "Active"), ("inactive", "Inactive"), ("on_leave", "On Leave")]

    name           = models.CharField(max_length=150)
    phone          = models.CharField(max_length=15, unique=True)
    email          = models.EmailField(blank=True)
    role           = models.CharField(max_length=20, choices=ROLE, default="trainer")
    shift          = models.CharField(max_length=10, choices=SHIFT, default="morning")
    # Detailed shift template — takes precedence over legacy `shift` field
    shift_template = models.ForeignKey(
        StaffShift, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="staff_members"
    )
    salary         = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    join_date      = models.DateField(default=timezone.localdate)
    status         = models.CharField(max_length=12, choices=STATUS, default="active")
    photo          = models.ImageField(upload_to="staff/", null=True, blank=True)
    photo_url      = models.URLField(blank=True)
    address        = models.TextField(blank=True)
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    personal_trainer_amt = models.DecimalField(max_digits=10, decimal_places=2, null = True, blank=True)
    # pt_amt_percentage = models.DecimalField(max_digits=10,decimal_places=2,blank = True, null = True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.role})"

    def display_id(self):
        return f"S{self.id:04d}"

    def get_shift_template(self):
        return self.shift_template


class StaffAttendance(models.Model):
    STATUS = [
        ("present",    "Present"),
        ("absent",     "Absent"),
        ("half",       "Half Day"),
        ("leave",      "Leave"),
        ("late",       "Late"),
        ("overtime",   "Overtime"),
        ("late_overtime","Late + Overtime"),
        ("auto_absent","Auto Absent"),   # set by auto-mark logic
    ]

    staff            = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="attendance")
    date             = models.DateField(default=timezone.localdate)
    check_in         = models.TimeField(null=True, blank=True)
    check_out        = models.TimeField(null=True, blank=True)
    status           = models.CharField(max_length=15, choices=STATUS, default="present")
    notes            = models.CharField(max_length=255, blank=True)

    # Computed — filled automatically on save() when times are present
    worked_minutes   = models.IntegerField(default=0)
    late_minutes     = models.IntegerField(default=0)
    overtime_minutes = models.IntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        unique_together = ["staff", "date"]

    def __str__(self):
        return f"{self.staff.name} — {self.date} [{self.status}]"

    def save(self, *args, **kwargs):
        shift = self.staff.get_shift_template()
        try:
            if shift and self.check_in:
                base      = dt.date.today()
                ci        = datetime.combine(base, self.check_in)
                st        = datetime.combine(base, shift.start_time)
                et        = datetime.combine(base, shift.end_time)
                if et < st:
                    et += timedelta(days=1)    # overnight shift

                # Late: trigger only if check_in exceeds grace window,
                # but measure from shift START (not from grace end)
                grace_end = st + timedelta(minutes=shift.late_grace_minutes)
                if ci > grace_end:
                    self.late_minutes = int((ci - st).total_seconds() / 60)
                else:
                    self.late_minutes = 0

                if self.check_out:
                    co = datetime.combine(base, self.check_out)
                    if co < ci:
                        co += timedelta(days=1)
                    self.worked_minutes = int((co - ci).total_seconds() / 60)
                    # OT: trigger only if check_out exceeds threshold window,
                    # but measure from shift END (not from threshold point)
                    ot_start = et + timedelta(minutes=shift.overtime_threshold_minutes)
                    if co > ot_start:
                        self.overtime_minutes = int((co - et).total_seconds() / 60)
                    else:
                        self.overtime_minutes = 0
                else:
                    self.worked_minutes   = 0
                    self.overtime_minutes = 0

                # Auto-derive status — only if not admin-forced
                if self.status not in ("absent", "half", "leave", "auto_absent"):
                    if self.overtime_minutes > 0 and self.late_minutes > 0:
                        self.status = "late_overtime"
                    elif self.overtime_minutes > 0:
                        self.status = "overtime"
                    elif self.late_minutes > 0:
                        self.status = "late"
                    else:
                        self.status = "present"

                logger.info(
                    f"StaffAttendance.save calc: staff={self.staff_id} date={self.date} "
                    f"shift={shift.name} check_in={self.check_in} check_out={self.check_out} "
                    f"late_minutes={self.late_minutes} worked_minutes={self.worked_minutes} "
                    f"overtime_minutes={self.overtime_minutes} -> status={self.status}"
                )
            else:
                # No check_in (absent/leave) — reset all computed fields
                if not self.check_in:
                    self.worked_minutes   = 0
                    self.late_minutes     = 0
                    self.overtime_minutes = 0
                logger.info(
                    f"StaffAttendance.save: staff={self.staff_id} date={self.date} "
                    f"no check_in/shift (shift={'set' if shift else 'none'}) -> status={self.status}"
                )
        except Exception:
            logger.exception(
                f"StaffAttendance.save: calculation failed for staff={self.staff_id} date={self.date}"
            )
            raise

        # Django's update_or_create passes update_fields=defaults.keys(), which
        # excludes our computed columns.  Force them in so they're always written.
        if "update_fields" in kwargs:
            uf = set(kwargs["update_fields"])
            uf.update({"worked_minutes", "late_minutes", "overtime_minutes", "status"})
            kwargs["update_fields"] = list(uf)

        super().save(*args, **kwargs)


class StaffPayment(models.Model):
    STATUS = [("paid", "Paid"), ("pending", "Pending"), ("partial", "Partial")]

    staff      = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="payments")
    month      = models.DateField()
    amount     = models.DecimalField(max_digits=10, decimal_places=2)
    paid_date  = models.DateField(null=True, blank=True)
    status     = models.CharField(max_length=10, choices=STATUS, default="pending")
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        unique_together = ["staff", "month"]