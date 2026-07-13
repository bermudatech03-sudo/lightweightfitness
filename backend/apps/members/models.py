from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

class MembershipPlan(models.Model):
    name          = models.CharField(max_length=100)
    duration_days = models.PositiveIntegerField(default=30)
    price         = models.DecimalField(max_digits=10, decimal_places=2)
    description   = models.TextField(blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.duration_days}d — ₹{self.price})"

class Member(models.Model):
    GENDER = [("Male","Male"),("Female","Female"),("Other","Other")]
    STATUS = [("active","Active"),("expired","Expired"),("cancelled","Cancelled"),("paused","Paused")]
    FOODTYPE = [("veg","Vegetarian"),("nonveg","Non-Vegetarian"),("vegan","Vegan"),("other","Other")]
    PLANTYPE = [("basic","Basic"),("standard","Standard"),("premium","Premium"),("dietonly-standard","Standard (Diet Only)")]
    name         = models.CharField(max_length=150)
    phone        = models.CharField(max_length=15, unique=True)
    email        = models.EmailField(blank=True,null = True)
    age          = models.PositiveIntegerField(default=18)
    dob           = models.DateField(null=True, blank=True, db_index=True)
    gym_member_id = models.CharField(max_length=50, blank=True)
    gender        = models.CharField(max_length=10, choices=GENDER, blank=True)
    address      = models.TextField(blank=True)
    photo_url    = models.URLField(blank=True)
    foodType     = models.CharField(max_length=10, choices=FOODTYPE, default="veg")
    plan         = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    plan_type     = models.CharField(max_length=20, choices=PLANTYPE, default="basic")
    diet         = models.ForeignKey('DietPlan', on_delete=models.SET_NULL, null=True, blank=True)
    join_date    = models.DateField(default=timezone.localdate)
    renewal_date = models.DateField(null=True, blank=True, db_index=True)
    status       = models.CharField(max_length=12, choices=STATUS, default="active", db_index=True)
    notes        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    personal_trainer       = models.BooleanField(default=False)
    joining_date           = models.DateField(default=timezone.localdate, null=True, blank=True)
    notifications_enabled  = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.phone}) {self.total_paid()} paid, {self.balance_due()} due"

    def days_until_expiry(self):
        if self.renewal_date:
            return (self.renewal_date - timezone.localdate()).days
        return None

    def total_paid(self):
        """
        Cached on the instance (see _total_paid_cache) so repeated calls within the
        same request/job run don't re-query — a caller can also pre-populate
        _total_paid_cache directly (e.g. from a queryset .annotate()) to skip the
        query entirely.
        """
        if not hasattr(self, "_total_paid_cache"):
            from django.db.models import Sum
            result = self.payments.aggregate(t=Sum("amount_paid"))["t"]
            self._total_paid_cache = result or 0
        return self._total_paid_cache

    def total_due(self):
        if not hasattr(self, "_total_due_cache"):
            from django.db.models import Sum
            result = self.payments.aggregate(t=Sum("total_with_gst"))["t"]
            self._total_due_cache = result or 0
        return self._total_due_cache

    def balance_due(self):
        return self.total_due() - self.total_paid()

    def renew(self):
        if self.plan:
            base = max(self.renewal_date, timezone.localdate()) if self.renewal_date else timezone.localdate()
            self.renewal_date = base + timedelta(days=self.plan.duration_days)
            self.status = "active"
            self.save()

    def display_id(self):
        return f"M{self.id:04d}"

    def change_amount(self):
        if not self.plan:
            return Decimal("0")
        if self.personal_trainer:
            assignment = self.trainer_assignments.select_related("trainer").first()
            if assignment and assignment.trainer.personal_trainer_amt:
                return self.plan.price + assignment.trainer.personal_trainer_amt
        return self.plan.price

class MemberPayment(models.Model):
    """
    One record per enrollment / renewal cycle.
    GST is calculated once on the plan price.
    Members can pay in installments — amount_paid grows,
    balance shrinks. GST is NOT re-applied on installments.
    """
    STATUS = [("paid","Paid"),("partial","Partial"),("pending","Pending")]
 
    member         = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="payments")
    plan           = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=60, blank=True)
 
    # Plan base price (before GST) — this is the price AFTER discount, includes diet_plan_amount
    plan_price       = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Diet plan charge included in plan_price (0 when no diet plan)
    diet_plan_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Discount applied at enrollment/renewal (original plan.price - plan_price)
    discount_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # GST fields — computed once at enrollment/renewal
    gst_rate       = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    gst_amount     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Total the member owes = plan_price + gst_amount
    total_with_gst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
 
    # Running installment tracking
    amount_paid    = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
 
    paid_date      = models.DateField(default=timezone.localdate)
    valid_from     = models.DateField()
    valid_to       = models.DateField()
    status         = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_date"]
 
    def save(self, *args, **kwargs):
        # Recalculate balance and status on every save
        self.balance = self.total_with_gst - self.amount_paid
        if self.balance <= Decimal("0"):
            self.status = "paid"
            self.balance = Decimal("0")
        elif self.amount_paid > Decimal("0"):
            self.status = "partial"
        else:
            self.status = "pending"
        super().save(*args, **kwargs)

    def add_installment(self, amount, paid_date=None, notes="", installment_type="balance"):
        """
        Convenience method: record a new installment, update amount_paid, save.
        GST is intentionally NOT touched here.
        """
        amount = Decimal(str(amount))
        inst = InstallmentPayment(
            payment          = self,
            member           = self.member,
            installment_type = installment_type,
            amount           = amount,
            paid_date        = paid_date or timezone.localdate(),
            notes            = notes,
        )
        self.amount_paid += amount
        # Snapshot the balance AFTER this installment is applied
        inst.balance_after = max(self.total_with_gst - self.amount_paid, Decimal("0"))
        inst.save()
        self.save()   # triggers balance / status recalc
        return inst
    
class MemberAttendance(models.Model):
    member     = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="attendance")
    date       = models.DateField(default=timezone.localdate)
    check_in   = models.TimeField(null=True, blank=True)
    check_out  = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-date", "-check_in"]
 
    def __str__(self):
        return f"{self.member.name} — {self.date}"
    
class DietPlan(models.Model):
    FOODTYPE = [("veg","Vegetarian"),("nonveg","Non-Vegetarian"),("vegan","Vegan"),("other","Other")]
    name       = models.CharField(max_length=100, default="Unnamed Plan")
    created_at = models.DateTimeField(auto_now_add=True)
    foodType = models.CharField(max_length=10, choices=FOODTYPE, default="veg")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Diet(models.Model):
    UNIT_CHOICES = [
        ("g",     "Grams"),
        ("kg",    "Kilograms"),
        ("ml",    "Milliliters"),
        ("l",     "Liters"),
        ("cup",   "Cup"),
        ("tbsp",  "Tablespoon"),
        ("tsp",   "Teaspoon"),
        ("piece", "Piece"),
    ]
    

    plan     = models.ForeignKey(DietPlan, on_delete=models.CASCADE, related_name="items")
    time     = models.TimeField()
    food     = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    unit     = models.CharField(max_length=10, choices=UNIT_CHOICES, default="g")
    calories = models.IntegerField()
    notes    = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["time"]

    def __str__(self):
        return f"{self.food} ({self.quantity}{self.unit}) at {self.time} and the note is {self.notes}"





class InstallmentPayment(models.Model):
    """
    One record per individual payment made against a MemberPayment cycle.
    Enrollment first payment, subsequent balance payments — all stored here.
    """
    INSTALLMENT_TYPE = [
        ("enrollment", "Enrollment"),
        ("renewal",    "Renewal"),
        ("balance",    "Balance Payment"),
    ]
    MODE_OF_PAYMENT = [
        ("cash", "Cash"),
        ("card", "Card"),
        ("upi",  "UPI"),
        ("other", "Other"),
    ]

    payment        = models.ForeignKey(MemberPayment, on_delete=models.CASCADE,
                                       related_name="installment_payments")
    member         = models.ForeignKey(Member, on_delete=models.CASCADE,
                                       related_name="installments")
    installment_type = models.CharField(max_length=20, choices=INSTALLMENT_TYPE, default="balance")
    amount         = models.DecimalField(max_digits=10, decimal_places=2)
    # Snapshot of balance AFTER this installment was applied
    balance_after  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_date      = models.DateField(default=timezone.localdate)
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    mode_of_payment = models.CharField(max_length=10, choices=MODE_OF_PAYMENT, default="cash")


    class Meta:
        ordering = ["paid_date", "created_at"]
 
    def __str__(self):
        return f"{self.member.name} — ₹{self.amount} on {self.paid_date} and mode of payment is {self.mode_of_payment}"
    

class TrainerAssignment(models.Model):
    member                     = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="trainer_assignments")
    trainer                    = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, limit_choices_to={"role": "trainer"}, related_name="member_assignments")
    plan                       = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_at                = models.DateTimeField(auto_now_add=True, db_index=True)
    startingtime               = models.TimeField()
    endingtime                 = models.TimeField()
    working_days               = models.CharField(max_length=20, default="0,1,2,3,4,5,6")
    trainer_fee_paid           = models.BooleanField(default=False)
    # PT period tracking — updated on initial assignment and each renewal
    pt_start_date              = models.DateField(null=True, blank=True)
    pt_end_date                = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ["member", "trainer"]
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.member.name} assigned to {self.trainer.name} for {self.plan.name if self.plan else 'No Plan'} on {self.assigned_at.date()} from {self.startingtime} to {self.endingtime}"

    def clean(self):
        if self.startingtime >= self.endingtime:
            raise ValidationError("Start time must be before end time")

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


class PTRenewal(models.Model):
    """
    One record per PT renewal transaction.
    The initial PT period is covered by the enrollment MemberPayment.
    Each subsequent PT renewal creates one PTRenewal record and one Income entry.
    Amount is prorated: if < 30 days remain in the plan, only those days are charged.
    """
    STATUS = [("paid", "Paid"), ("partial", "Partial"), ("pending", "Pending")]
    MODE_OF_PAYMENT = [
        ("cash", "Cash"), ("card", "Card"), ("upi", "UPI"), ("other", "Other"),
    ]

    assignment             = models.ForeignKey(TrainerAssignment, on_delete=models.CASCADE, related_name="pt_renewals")
    member                 = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pt_renewals")
    trainer                = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name="pt_renewals_as_trainer")
    pt_start_date          = models.DateField()
    pt_end_date            = models.DateField()
    pt_days                = models.PositiveIntegerField()
    base_amount            = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate               = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    gst_amount             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount           = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid            = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mode_of_payment        = models.CharField(max_length=10, choices=MODE_OF_PAYMENT, default="cash")
    invoice_number         = models.CharField(max_length=80, blank=True)
    status                 = models.CharField(max_length=10, choices=STATUS, default="pending")
    paid_date              = models.DateField(default=timezone.localdate)
    notes                  = models.TextField(blank=True)
    created_at             = models.DateTimeField(auto_now_add=True)
    # Trainer payout tracking for this renewal period
    trainer_payable_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    trainer_paid           = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PT Renewal — {self.member.name} ({self.pt_start_date} → {self.pt_end_date})"