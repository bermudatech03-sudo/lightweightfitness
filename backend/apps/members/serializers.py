import logging
from rest_framework import serializers
from decimal import Decimal, ROUND_HALF_UP
from .models import Diet, DietPlan, Member, MembershipPlan, MemberPayment, MemberAttendance, InstallmentPayment, TrainerAssignment, PTRenewal
from apps.finances.gst_utils import get_gst_rate as _get_gst_rate
from .validators import is_valid_domain, is_valid_phone
import phonenumbers

logger = logging.getLogger(__name__)

def _gst_rate():
    return _get_gst_rate()


class PlanSerializer(serializers.ModelSerializer):
    # GST-inclusive total — computed from settings.GST_RATE once here
    # so all frontends always show the correct final price without extra calls.
    gst_rate       = serializers.SerializerMethodField()
    price_with_gst = serializers.SerializerMethodField()

    
    class Meta:
        model  = MembershipPlan
        fields = "__all__"

    def get_gst_rate(self, obj):
        return float(_gst_rate())

    def get_price_with_gst(self, obj):
        rate  = _gst_rate()
        base  = Decimal(str(obj.price))
        total = (base + base * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return float(total)


class InstallmentPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InstallmentPayment
        fields = "__all__"


class DietSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diet
        fields = "__all__"

class DietPlanSerializer(serializers.ModelSerializer):
    items                  = DietSerializer(many=True, read_only=True)
    assigned_members_count = serializers.SerializerMethodField()
    assigned_members       = serializers.SerializerMethodField()

    class Meta:
        model  = DietPlan
        fields = "__all__"

    def get_assigned_members_count(self, obj):
        return obj.member_set.count()

    def get_assigned_members(self, obj):
        return list(obj.member_set.values_list("name", flat=True))


class MemberPaymentSerializer(serializers.ModelSerializer):
    plan_name            = serializers.CharField(source="plan.name",   read_only=True)
    member_name          = serializers.CharField(source="member.name", read_only=True)
    installment_payments = InstallmentPaymentSerializer(many=True, read_only=True)

    class Meta:
        model  = MemberPayment
        fields = "__all__"


class MemberSerializer(serializers.ModelSerializer):
    plan_name          = serializers.CharField(source="plan.name",  read_only=True)
    plan_price_val     = serializers.DecimalField(source="plan.price",
                             max_digits=10, decimal_places=2, read_only=True)
    plan_allows_trainer = serializers.SerializerMethodField()
    diet_id            = serializers.IntegerField(source="diet.id",  read_only=True, allow_null=True)
    diet_name          = serializers.CharField(source="diet.name",  read_only=True, allow_null=True)
    days_until_expiry  = serializers.SerializerMethodField()
    total_paid         = serializers.SerializerMethodField()
    balance_due        = serializers.SerializerMethodField()
    member_id_display  = serializers.SerializerMethodField()
    latest_discount_amount = serializers.SerializerMethodField()

    class Meta:
        model  = Member
        fields = "__all__"

    def _payments(self, obj):
        """
        Uses the `prefetched_payments` list (see MemberViewSet.get_queryset, ordered
        -created_at) when available so total_paid/balance_due/latest_discount_amount
        share one query instead of each hitting the DB separately — falls back to a
        single direct query (cached on the instance) otherwise.
        """
        if not hasattr(obj, "_cached_payments"):
            prefetched = getattr(obj, "prefetched_payments", None)
            obj._cached_payments = (
                prefetched if prefetched is not None
                else list(obj.payments.order_by("-created_at"))
            )
        return obj._cached_payments

    def get_days_until_expiry(self, obj): return obj.days_until_expiry()

    def get_total_paid(self, obj):
        total = sum((p.amount_paid for p in self._payments(obj)), Decimal("0"))
        return float(total)

    def get_balance_due(self, obj):
        payments   = self._payments(obj)
        total_due  = sum((p.total_with_gst for p in payments), Decimal("0"))
        total_paid = sum((p.amount_paid    for p in payments), Decimal("0"))
        balance    = total_due - total_paid
        logger.info(
            f"MemberSerializer.get_balance_due: member_id={obj.id} total_due={total_due} "
            f"total_paid={total_paid} -> balance_due={balance}"
        )
        return float(balance)

    def get_member_id_display(self, obj): return obj.display_id()
    def get_plan_allows_trainer(self, obj):
        return obj.plan_type in ("standard", "premium") and obj.personal_trainer
    def get_latest_discount_amount(self, obj):
        payments = self._payments(obj)
        return float(payments[0].discount_amount) if payments else 0.0


class MemberAttendanceSerializer(serializers.ModelSerializer):
    member_name       = serializers.CharField(source="member.name", read_only=True)
    member_display_id = serializers.SerializerMethodField()

    class Meta:
        model  = MemberAttendance
        fields = "__all__"

    def get_member_display_id(self, obj):
        return obj.member.display_id()


class EnrollSerializer(serializers.Serializer):
    name          = serializers.CharField()
    phone         = serializers.CharField()
    email         = serializers.EmailField(required=False, allow_blank=True)
    gender        = serializers.CharField(required=False, allow_blank=True)
    address       = serializers.CharField(required=False, allow_blank=True)
    dob           = serializers.DateField(required=False, allow_null=True)
    gym_member_id = serializers.CharField(required=False, allow_blank=True, default="")
    plan_id       = serializers.IntegerField(required=False, allow_null=True)
    diet_id       = serializers.IntegerField(required=False, allow_null=True)
    join_date     = serializers.DateField(required=False)
    joining_date  = serializers.DateField(required=False, allow_null=True)
    renewal_date  = serializers.DateField(required=False, allow_null=True)
    amount_paid   = serializers.DecimalField(max_digits=10, decimal_places=2,
                        required=False, default=0)
    notes             = serializers.CharField(required=False, allow_blank=True)
    status            = serializers.CharField(required=False, default="active")
    plan_type         = serializers.CharField(required=False, default="basic")
    personal_trainer  = serializers.BooleanField(required=False, default=False)
    mode_of_payment   = serializers.CharField(required=False, default="cash")
    discount_amount   = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)

    def validate_email(self, value):
        print("Output: ",is_valid_domain(value))
        if not is_valid_domain(value):
            raise serializers.ValidationError("Invalid email domain")
        return value
    

    def validate_phone(self, value):
        value = is_valid_phone(value)
        if Member.objects.filter(phone=value).exists():
            logger.warning(f"EnrollSerializer.validate_phone: rejected duplicate phone {value}")
            raise serializers.ValidationError("A member with this phone number already exists.")
        return value

class RenewSerializer(serializers.Serializer):
    plan_id         = serializers.IntegerField(required=False, allow_null=True)
    plan_type       = serializers.CharField(required=False, allow_blank=True, default="")
    amount_paid     = serializers.DecimalField(max_digits=10, decimal_places=2)
    notes           = serializers.CharField(required=False, allow_blank=True, default="")
    mode_of_payment = serializers.CharField(required=False, default="cash")
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)

class BalancePaymentSerializer(serializers.Serializer):
    amount_paid     = serializers.DecimalField(max_digits=10, decimal_places=2)
    notes           = serializers.CharField(required=False, allow_blank=True, default="")
    mode_of_payment = serializers.CharField(required=False, default="cash")

class AssignTrainerSerializer(serializers.Serializer):
    trainer_id = serializers.IntegerField()
    plan_id    = serializers.IntegerField(required=False, allow_null=True)
    startingtime = serializers.TimeField()
    endingtime   = serializers.TimeField()
    working_days = serializers.CharField(required=False, default="0,1,2,3,4,5,6")


class PTRenewalSerializer(serializers.ModelSerializer):
    member_name  = serializers.CharField(source="member.name",  read_only=True)
    trainer_name = serializers.CharField(source="trainer.name", read_only=True)

    class Meta:
        model  = PTRenewal
        fields = "__all__"


class TrainerAssignmentSerializer(serializers.ModelSerializer):
    member_name        = serializers.CharField(source="member.name",  read_only=True)
    member_display_id  = serializers.SerializerMethodField()
    trainer_name       = serializers.CharField(source="trainer.name", read_only=True)
    trainer_display_id = serializers.SerializerMethodField()
    plan_name          = serializers.CharField(source="plan.name",    read_only=True, allow_null=True)
    working_day_names  = serializers.SerializerMethodField()
    trainer_pt_amt     = serializers.SerializerMethodField()
    member_amount_paid = serializers.SerializerMethodField()
    member_plan_total  = serializers.SerializerMethodField()
    # PT period computed fields
    pt_days_remaining               = serializers.SerializerMethodField()
    pt_renewal_days                 = serializers.SerializerMethodField()
    pt_renewal_amount               = serializers.SerializerMethodField()
    can_renew_pt                    = serializers.SerializerMethodField()
    pt_renewal_blocked_reason       = serializers.SerializerMethodField()
    member_plan_expiry              = serializers.SerializerMethodField()
    member_status                   = serializers.SerializerMethodField()
    # Pending trainer payout from PT renewals (unpaid PTRenewal records)
    pending_pt_renewal_trainer_amount   = serializers.SerializerMethodField()
    # Sum of member-side amount_paid for renewals not yet paid out to trainer
    pt_renewal_member_paid_amount       = serializers.SerializerMethodField()
    # Whether any PTRenewal has already been paid out to trainer
    has_paid_pt_renewals                = serializers.SerializerMethodField()
    # Balance remaining on the latest partial/pending PTRenewal
    pending_pt_balance                  = serializers.SerializerMethodField()
    pending_pt_balance_invoice          = serializers.SerializerMethodField()

    class Meta:
        model  = TrainerAssignment
        fields = "__all__"

    def get_member_display_id(self, obj):
        return obj.member.display_id()

    def get_trainer_display_id(self, obj):
        return f"S{obj.trainer.id:04d}"

    def get_working_day_names(self, obj):
        return obj.working_day_names

    def get_trainer_pt_amt(self, obj):
        from apps.finances.gst_utils import get_pt_payable_percent
        amt = obj.trainer.personal_trainer_amt
        if not amt:
            return 0
        fee = Decimal(str(amt))
        # Prorate by actual PT days assigned (capped at 30)
        if obj.pt_start_date and obj.pt_end_date:
            pt_days = (obj.pt_end_date - obj.pt_start_date).days
            if 0 < pt_days < 30:
                fee = (fee / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP)
        pct = get_pt_payable_percent()
        payable = (fee * pct / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        logger.info(
            f"get_trainer_pt_amt: assignment_id={obj.id} member_id={obj.member_id} trainer_id={obj.trainer_id} "
            f"full_amt={amt} pt_start={obj.pt_start_date} pt_end={obj.pt_end_date} prorated_fee={fee} "
            f"pt_payable_pct={pct}% -> payable={payable}"
        )
        return float(payable)

    def _latest_payment(self, obj):
        """
        Uses the `prefetched_payments` list (see MemberTrainerAssignmentViewSet.get_queryset)
        when available to avoid a duplicate query — falls back to a direct query otherwise.
        """
        prefetched = getattr(obj.member, "prefetched_payments", None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return obj.member.payments.order_by("-created_at").first()

    def get_member_amount_paid(self, obj):
        payment = self._latest_payment(obj)
        return float(payment.amount_paid) if payment else 0

    def get_member_plan_total(self, obj):
        payment = self._latest_payment(obj)
        return float(payment.total_with_gst) if payment else 0

    def get_pt_days_remaining(self, obj):
        """Days left in the current PT period (negative = expired)."""
        if not obj.pt_end_date:
            return None
        from django.utils import timezone
        return (obj.pt_end_date - timezone.localdate()).days

    def get_member_plan_expiry(self, obj):
        return str(obj.member.renewal_date) if obj.member.renewal_date else None

    def get_member_status(self, obj):
        return obj.member.status

    def get_pt_renewal_days(self, obj):
        """
        Chargeable days for the NEXT PT renewal.
        = min(30, plan_days_remaining - current_pt_days_remaining)
        so we only charge for the gap being added, not re-charge covered days.
        Returns 0 if plan is expired, member is inactive, or PT already
        covers the full remaining plan period.
        """
        from django.utils import timezone
        today = timezone.localdate()
        if obj.member.status != "active":
            return 0
        if not obj.member.renewal_date or obj.member.renewal_date <= today:
            return 0
        if obj.pt_end_date and obj.pt_end_date >= obj.member.renewal_date:
            return 0
        plan_remaining    = (obj.member.renewal_date - today).days
        current_pt_remaining = (
            max(0, (obj.pt_end_date - today).days) if obj.pt_end_date else 0
        )
        return min(30, max(0, plan_remaining - current_pt_remaining))

    def get_pt_renewal_amount(self, obj):
        """GST-inclusive prorated PT fee for the next renewal period."""
        from apps.finances.gst_utils import get_gst_rate
        pt_days = self.get_pt_renewal_days(obj)
        if pt_days <= 0:
            return 0.0
        full_amt = obj.trainer.personal_trainer_amt
        if not full_amt:
            return 0.0
        base  = (Decimal(str(full_amt)) / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP)
        rate  = get_gst_rate()
        gst   = (base * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        total = base + gst
        logger.info(
            f"get_pt_renewal_amount: assignment_id={obj.id} member_id={obj.member_id} full_amt={full_amt} "
            f"pt_days={pt_days} base={base} gst_rate={rate}% gst={gst} -> total={total}"
        )
        return float(total)

    def get_can_renew_pt(self, obj):
        """True only when there are new PT days to cover beyond the current PT expiry."""
        from django.utils import timezone
        today = timezone.localdate()
        if obj.member.status != "active":
            return False
        if not obj.member.renewal_date or obj.member.renewal_date <= today:
            return False
        # PT already covers up to (or past) plan expiry — nothing more to renew
        if obj.pt_end_date and obj.pt_end_date >= obj.member.renewal_date:
            return False
        return True

    def get_pt_renewal_blocked_reason(self, obj):
        """Human-readable reason when can_renew_pt is False, or None if renewal is allowed."""
        from django.utils import timezone
        today = timezone.localdate()
        if obj.member.status != "active":
            return "Member plan is inactive"
        if not obj.member.renewal_date or obj.member.renewal_date <= today:
            return "Member plan has expired — extend membership first"
        if obj.pt_end_date and obj.pt_end_date >= obj.member.renewal_date:
            return f"PT is active until plan expiry ({obj.member.renewal_date}) — extend membership to unlock renewal"
        return None

    def _pt_renewals(self, obj):
        """
        obj.pt_renewals.all() uses the prefetch_related("pt_renewals") cache from
        MemberTrainerAssignmentViewSet.get_queryset when present (one query for all
        rows instead of one query per row per method below), and still respects
        PTRenewal.Meta.ordering (-created_at) either way — same semantics as the
        previous .filter().order_by("-created_at").first() calls, just computed
        in Python instead of 5 separate DB round-trips per row.
        """
        return list(obj.pt_renewals.all())

    def _latest_pending_pt_renewal(self, obj):
        pending = [r for r in self._pt_renewals(obj) if r.status in ("partial", "pending")]
        return pending[0] if pending else None

    def get_pending_pt_renewal_trainer_amount(self, obj):
        """Sum of trainer_payable_amount for all unpaid PTRenewal records on this assignment."""
        total = sum((r.trainer_payable_amount for r in self._pt_renewals(obj) if not r.trainer_paid), Decimal("0"))
        return float(total)

    def get_pt_renewal_member_paid_amount(self, obj):
        """Sum of amount_paid collected from member for renewals not yet paid out to trainer."""
        total = sum((r.amount_paid for r in self._pt_renewals(obj) if not r.trainer_paid), Decimal("0"))
        return float(total)

    def get_has_paid_pt_renewals(self, obj):
        """True when at least one PTRenewal has been paid out to the trainer."""
        return any(r.trainer_paid for r in self._pt_renewals(obj))

    def get_pending_pt_balance(self, obj):
        """Balance remaining on the latest partial/pending PTRenewal."""
        latest = self._latest_pending_pt_renewal(obj)
        if not latest:
            return 0.0
        bal = latest.total_amount - latest.amount_paid
        return float(max(bal, Decimal("0")))

    def get_pending_pt_balance_invoice(self, obj):
        """Invoice number of the latest partial/pending PTRenewal."""
        latest = self._latest_pending_pt_renewal(obj)
        return latest.invoice_number if latest else None

    def validate(self, data):
        if data.get("startingtime") and data.get("endingtime"):
            if data["startingtime"] >= data["endingtime"]:
                logger.warning(
                    f"TrainerAssignmentSerializer.validate: rejected — startingtime={data['startingtime']} "
                    f">= endingtime={data['endingtime']}"
                )
                raise serializers.ValidationError("Start time must be before end time.")
        return data