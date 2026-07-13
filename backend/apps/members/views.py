import logging
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, Prefetch, Count
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

logger = logging.getLogger(__name__)
from .models import Diet, DietPlan, Member, MembershipPlan, MemberPayment, MemberAttendance, InstallmentPayment, TrainerAssignment, PTRenewal
from .serializers import (DietSerializer, DietPlanSerializer, MemberSerializer, PlanSerializer, MemberPaymentSerializer,
    MemberAttendanceSerializer, EnrollSerializer, RenewSerializer, BalancePaymentSerializer,
    InstallmentPaymentSerializer, TrainerAssignmentSerializer, PTRenewalSerializer)
import logging

from apps.finances.gst_utils import get_gst_rate as _get_gst_rate, get_gym_info as _gym_info
logger = logging.getLogger(__name__)
def _gst_rate():
    return _get_gst_rate()

def _calc_gst(base_price):
    rate    = _gst_rate()
    base    = Decimal(str(base_price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    gst_amt = (base * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    total   = base + gst_amt
    logger.info(f"GST calc: base_price_in={base_price} -> base={base} rate={rate}% gst={gst_amt} total={total}")
    return base, gst_amt, total, rate

def _invoice_number(member_id, date, suffix=""):
    return f"INV-{date.year}{date.month:02d}-M{member_id:04d}{suffix}"

def _auto_expire_members():
    """
    Bulk-mark active members whose renewal_date has passed as expired.
    Skips cancelled/paused. Called on every list fetch — very cheap bulk UPDATE.
    """
    updated = Member.objects.filter(
        status="active",
        renewal_date__lt=timezone.localdate(),
    ).update(status="expired")
    if updated:
        logger.info(f"_auto_expire_members: marked {updated} member(s) as expired (renewal_date < {timezone.localdate()})")

def _record_income_for_installment(member, payment, installment):
    """
    Records an Income entry for a single installment.

    GST RULE (GST-first allocation):
      - GST is paid off first across all installments for the same invoice.
      - Each payment fills the remaining GST bucket first; the rest goes to base.
      - Once GST is fully paid, all subsequent installments are 100% base amount.

    plan_total (plan_price + gst = full plan value) is embedded in notes as
    "plan_total:XXXXXX" so MonthlyReportView can surface it in the report.
    """
    from apps.finances.models import Income

    amount_paid = Decimal(str(installment.amount))

    label_map = {
        "enrollment": "Enrollment",
        "renewal":    "Renewal",
        "balance":    "Balance Payment",
    }
    label = label_map.get(installment.installment_type, "Payment")

    # How much GST has already been collected for this invoice across prior installments
    already_paid_gst = (
        Income.objects.filter(invoice_number=payment.invoice_number)
        .aggregate(total=Sum("gst_amount"))["total"] or Decimal("0")
    )

    gst_remaining = max(Decimal("0"), payment.gst_amount - already_paid_gst)
    gst_now       = min(amount_paid, gst_remaining).quantize(Decimal("0.01"), ROUND_HALF_UP)
    base_now      = (amount_paid - gst_now).quantize(Decimal("0.01"), ROUND_HALF_UP)
    effective_rate = payment.gst_rate if gst_now > 0 else Decimal("0")

    plan_total = payment.total_with_gst

    logger.info(
        f"_record_income_for_installment: member_id={member.id} invoice={payment.invoice_number} "
        f"installment_id={installment.id} amount_paid={amount_paid} already_paid_gst={already_paid_gst} "
        f"payment.gst_amount={payment.gst_amount} -> gst_now={gst_now} base_now={base_now} "
        f"effective_rate={effective_rate}% plan_total={plan_total}"
    )

    Income.objects.create(
        source         = f"{label} — {member.name}",
        category       = "membership",
        base_amount    = base_now,
        gst_rate       = effective_rate,
        gst_amount     = gst_now,
        amount         = amount_paid,
        date           = installment.paid_date,
        member_id      = member.id,
        invoice_number = payment.invoice_number,
        notes          = (
            f"Plan: {member.plan.name if member.plan else 'N/A'} "
            f"| {payment.valid_from} → {payment.valid_to} "
            f"| Balance after: ₹{installment.balance_after} "
            f"| plan_total:{plan_total} "
            f"| mode:{installment.mode_of_payment or 'cash'}"
        ),
    )

def _create_installment(payment, member, amount, installment_type, notes="", mode_of_payment="cash"):
    if amount > payment.balance:
        logger.warning(
            f"_create_installment rejected: member_id={member.id} invoice={payment.invoice_number} "
            f"amount={amount} exceeds balance={payment.balance}"
        )
        raise serializers.ValidationError(
            f"Installment amount ₹{amount} exceeds remaining balance of ₹{payment.balance}."
        )
    balance_after = max(Decimal("0"), payment.balance - Decimal(str(amount)))

    installment = InstallmentPayment.objects.create(
        payment          = payment,
        member           = member,
        installment_type = installment_type,
        amount           = Decimal(str(amount)),
        balance_after    = balance_after,
        paid_date        = timezone.localdate(),
        notes            = notes,
        mode_of_payment  = mode_of_payment,
    )

    payment.amount_paid = payment.amount_paid + Decimal(str(amount))
    payment.save()

    logger.info(
        f"_create_installment: member_id={member.id} invoice={payment.invoice_number} type={installment_type} "
        f"amount={amount} mode={mode_of_payment} -> balance_after={balance_after} new_amount_paid={payment.amount_paid}"
    )

    return installment

def _build_bill(member, payment, gym):
    installments = list(payment.installment_payments.all().order_by("paid_date", "created_at"))
    installment_data = []
    for inst in installments:
        installment_data.append({
            "id":               inst.id,
            "installment_type": inst.installment_type,
            "amount":           float(inst.amount),
            "balance_after":    float(inst.balance_after),
            "paid_date":        str(inst.paid_date),
            "notes":            inst.notes,
            "mode_of_payment":  inst.mode_of_payment,
        })

    diet_amt        = float(payment.diet_plan_amount)
    discount_amt    = float(payment.discount_amount)
    plan_base_price = float(payment.plan.price) if payment.plan else 0.0
    # plan_price = (plan.price - discount) + pt_fee + diet; derive pt_fee from the difference
    derived_pt_fee = max(0.0, float(payment.plan_price) - plan_base_price + discount_amt - diet_amt)
    # membership_fee = original plan price (before discount) for transparent invoice display
    membership_fee = plan_base_price if payment.plan else float(payment.plan_price) + discount_amt - diet_amt - derived_pt_fee
    logger.info(
        f"_build_bill: invoice={payment.invoice_number} member_id={member.id} membership_fee={membership_fee} "
        f"discount={discount_amt} pt_fee={derived_pt_fee} diet={diet_amt} gst={float(payment.gst_amount)} "
        f"total_with_gst={float(payment.total_with_gst)} amount_paid={float(payment.amount_paid)} balance={float(payment.balance)}"
    )
    return {
        "invoice_number":    payment.invoice_number,
        "member_id":         member.display_id(),
        "member_name":       member.name,
        "phone":             member.phone,
        "email":             member.email,
        "plan_name":         payment.plan.name if payment.plan else "",
        "plan_duration":     payment.plan.duration_days if payment.plan else 0,
        # plan_price is the post-discount combined base (membership - discount + PT + diet)
        "plan_price":        float(payment.plan_price),
        "membership_fee":    membership_fee,
        "discount_amount":   discount_amt,
        "pt_fee":            derived_pt_fee,
        "diet_plan_amount":  diet_amt,
        "gst_rate":          float(payment.gst_rate),
        "gst_amount":        float(payment.gst_amount),
        "total_with_gst":    float(payment.total_with_gst),
        "amount_paid":       float(payment.amount_paid),
        "balance":           float(payment.balance),
        "valid_from":        str(payment.valid_from),
        "valid_to":          str(payment.valid_to),
        "date":              str(timezone.localdate()),
        "status":            payment.status,
        "gym_name":          gym["name"],
        "gym_address":       gym["address"],
        "gym_phone":         gym["phone"],
        "gym_email":         gym["email"],
        "gym_gstin":         gym["gstin"],
        "cycle_installments": installment_data,
    }


# ─── ViewSets ────────────────────────────────────────

class MembershipPlanViewSet(viewsets.ModelViewSet):
    queryset         = MembershipPlan.objects.all()
    serializer_class = PlanSerializer

    def get_queryset(self):
        qs = MembershipPlan.objects.all()
        if self.request.query_params.get("active_only") == "true":
            qs = qs.filter(is_active=True)
        return qs


class MemberViewSet(viewsets.ModelViewSet):
    queryset         = Member.objects.select_related("plan", "diet").all()
    serializer_class = MemberSerializer
    search_fields    = ["name","phone","email"]
    ordering_fields  = ["name","join_date","renewal_date","status","personal_trainer"]

    def get_queryset(self):
        # Auto-expire members whose renewal date has passed
        _auto_expire_members()

        qs     = (
            Member.objects
            .select_related("plan", "diet")
            .prefetch_related(
                Prefetch(
                    "payments",
                    queryset=MemberPayment.objects.order_by("-created_at"),
                    to_attr="prefetched_payments",
                ),
            )
            .all()
        )
        params = self.request.query_params

        # status filter
        if params.get("status"):
            qs = qs.filter(status=params["status"])

        # gender filter
        if params.get("gender"):
            qs = qs.filter(gender=params["gender"])

        # plan filter (by plan id)
        if params.get("plan"):
            qs = qs.filter(plan_id=params["plan"])

        # plan filter (by personal trainer requirement)
        if params.get("personal_trainer") == "true":
            qs = qs.filter(personal_trainer=True)

        # search — name, phone, email, gym_member_id
        if params.get("search"):
            q  = params["search"]
            qs = qs.filter(
                Q(name__icontains=q) | Q(phone__icontains=q) |
                Q(email__icontains=q) | Q(gym_member_id__icontains=q)
            )

        # DOB date range filter
        if params.get("dob_from"):
            qs = qs.filter(dob__gte=params["dob_from"])
        if params.get("dob_to"):
            qs = qs.filter(dob__lte=params["dob_to"])

        # expiring within N days (only makes sense for active members)
        expiring_days = params.get("expiring_days")
        if expiring_days:
            try:
                n      = int(expiring_days)
                today  = timezone.localdate()
                cutoff = today + timedelta(days=n)
                qs = qs.filter(
                    status="active",
                    renewal_date__gte=today,
                    renewal_date__lte=cutoff,
                )
            except ValueError:
                pass

        # balance filter
        balance_filter = params.get("balance_filter")
        if balance_filter == "has_balance":
            # Members with at least one partial or pending payment cycle
            qs = qs.filter(payments__status__in=["partial", "pending"]).distinct()
        elif balance_filter == "no_balance":
            # Members with NO partial or pending cycles
            qs = qs.exclude(payments__status__in=["partial", "pending"]).distinct()

        return qs

    def create(self, request, *args, **kwargs):
        logger.info(f"MemberViewSet.create (enroll): incoming payload name={request.data.get('name')} phone={request.data.get('phone')} plan_id={request.data.get('plan_id')} amount_paid={request.data.get('amount_paid')}")
        s = EnrollSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        plan = None
        if d.get("plan_id"):
            plan = MembershipPlan.objects.get(pk=d["plan_id"])

        join  = d.get("join_date", timezone.localdate())
        renew = d.get("renewal_date")
        if not renew and plan:
            renew = join + timedelta(days=plan.duration_days)

        diet = None
        if d.get("diet_id"):
            diet = DietPlan.objects.filter(pk=d["diet_id"]).first()

        plan_type = d.get("plan_type", "basic")

        member = Member.objects.create(
            name=d["name"], phone=d["phone"],
            email=d.get("email",""), gender=d.get("gender",""),
            address=d.get("address",""), plan=plan, diet=diet,
            dob=d.get("dob"),
            gym_member_id=d.get("gym_member_id",""),
            join_date=join, renewal_date=renew,
            joining_date=d.get("joining_date") or join,
            status=d.get("status","active"), notes=d.get("notes",""),
            plan_type=plan_type,
            personal_trainer=d.get("personal_trainer", False),
        )
        logger.info(f"MemberViewSet.create: member created id={member.id} name={member.name} phone={member.phone} plan={plan.name if plan else None} plan_type={plan_type} join_date={join} renewal_date={renew}")

        amount_paid = Decimal(str(d.get("amount_paid", 0)))
        bill_data   = None

        if plan:
            from apps.finances.gst_utils import get_diet_plan_amount as _get_diet_amt
            diet_amt     = _get_diet_amt() if (diet or plan_type in ("premium", "dietonly-standard")) else Decimal("0")
            discount_amt = Decimal(str(d.get("discount_amount", 0)))
            logger.info(
                f"MemberViewSet.create: enrollment pricing inputs — member_id={member.id} plan_price={plan.price} "
                f"diet_amt={diet_amt} discount_amt={discount_amt}"
            )
            base, gst_amt, total, rate = _calc_gst(plan.price + diet_amt - discount_amt)
            inv_no = _invoice_number(member.id, join)

            payment = MemberPayment.objects.create(
                member           = member,
                plan             = plan,
                invoice_number   = inv_no,
                plan_price       = base,
                diet_plan_amount = diet_amt,
                discount_amount  = discount_amt,
                gst_rate         = rate,
                gst_amount       = gst_amt,
                total_with_gst   = total,
                amount_paid      = Decimal("0"),
                valid_from       = join,
                valid_to         = renew or join,
            )

            if amount_paid > 0:
                installment = _create_installment(
                    payment, member, amount_paid, "enrollment",
                    notes=d.get("notes", ""),
                    mode_of_payment=d.get("mode_of_payment", "cash"),
                )
                _record_income_for_installment(member, payment, installment)

            payment.refresh_from_db()
            bill_data = _build_bill(member, payment, _gym_info())

        # The `membership_bill` WhatsApp template carries the greeting + invoice PDF
        # in a single message, so no separate text notification is needed here.
        try:
            from apps.notifications.whatsapp import send_bill_on_whatsapp
            phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
            if phone and not phone.startswith("91"):
                phone = f"91{phone}"
            send_bill_on_whatsapp(phone, bill_data, "enrollment")
        except Exception as e:
            logger.warning(f"Bill WhatsApp send failed for enrollment: member_id={member.id} error={e}")

        return Response({
            **MemberSerializer(member).data,
            "bill": bill_data,
        }, status=201)

    def destroy(self, request, *args, **kwargs):
        member = self.get_object()
        logger.info(f"MemberViewSet.destroy: deleting member id={member.id} name={member.name} phone={member.phone}")
        member.delete()
        return Response({"detail": "Member deleted."}, status=204)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        member = self.get_object()
        logger.info(f"MemberViewSet.renew: member_id={member.id} name={member.name} incoming payload plan_id={request.data.get('plan_id')} amount_paid={request.data.get('amount_paid')} discount_amount={request.data.get('discount_amount')}")
        s = RenewSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        if s.validated_data.get("plan_id"):
            member.plan = MembershipPlan.objects.get(pk=s.validated_data["plan_id"])

        # Determine new plan type and set flags accordingly
        new_plan_type = s.validated_data.get("plan_type") or member.plan_type or "basic"
        member.plan_type = new_plan_type

        if new_plan_type == "basic":
            member.personal_trainer = False
            member.diet = None
        elif new_plan_type == "standard":
            member.personal_trainer = True
            member.diet = None
        elif new_plan_type == "premium":
            member.personal_trainer = True
            if "diet_id" in request.data:
                new_diet_id = request.data.get("diet_id") or None
                member.diet = DietPlan.objects.filter(pk=new_diet_id).first() if new_diet_id else None
        elif new_plan_type == "dietonly-standard":
            member.personal_trainer = False
            if "diet_id" in request.data:
                new_diet_id = request.data.get("diet_id") or None
                member.diet = DietPlan.objects.filter(pk=new_diet_id).first() if new_diet_id else None

        old_renewal = member.renewal_date
        amount_paid = Decimal(str(s.validated_data["amount_paid"]))
        member.save()

        member.renew()

        from apps.finances.gst_utils import get_diet_plan_amount as _get_diet_amt
        diet_amt     = _get_diet_amt() if (member.diet or new_plan_type in ("premium", "dietonly-standard")) else Decimal("0")
        discount_amt = Decimal(str(s.validated_data.get("discount_amount", 0)))
        plan_base    = (member.plan.price if member.plan else amount_paid) + diet_amt - discount_amt
        logger.info(
            f"MemberViewSet.renew: pricing inputs — member_id={member.id} old_renewal={old_renewal} "
            f"new_renewal={member.renewal_date} plan_price={member.plan.price if member.plan else None} "
            f"diet_amt={diet_amt} discount_amt={discount_amt} -> plan_base={plan_base}"
        )
        base, gst_amt, total, rate = _calc_gst(plan_base)
        inv_no = _invoice_number(member.id, timezone.localdate(), "-R")

        payment = MemberPayment.objects.create(
            member           = member,
            plan             = member.plan,
            invoice_number   = inv_no,
            plan_price       = base,
            diet_plan_amount = diet_amt,
            discount_amount  = discount_amt,
            gst_rate         = rate,
            gst_amount       = gst_amt,
            total_with_gst   = total,
            amount_paid      = Decimal("0"),
            valid_from       = old_renewal or timezone.localdate(),
            valid_to         = member.renewal_date,
            notes            = s.validated_data.get("notes",""),
        )

        if amount_paid > 0:
            installment = _create_installment(
                payment, member, amount_paid, "renewal",
                notes=s.validated_data.get("notes", ""),
                mode_of_payment=s.validated_data.get("mode_of_payment", "cash"),
            )
            _record_income_for_installment(member, payment, installment)

        payment.refresh_from_db()
        bill_data = _build_bill(member, payment, _gym_info())

        # The `membership_bill` template already contains the renewal confirmation
        # wording + invoice PDF — no separate text notification is sent.
        try:
            from apps.notifications.whatsapp import send_bill_on_whatsapp
            phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
            if phone and not phone.startswith("91"):
                phone = f"91{phone}"
            send_bill_on_whatsapp(phone, bill_data, "renewal")
        except Exception as e:
            logger.warning(f"Bill WhatsApp send failed for renewal: member_id={member.id} error={e}")

        return Response({
            **MemberSerializer(member).data,
            "bill": bill_data,
        })

    @action(detail=True, methods=["post"], url_path="pay-balance")
    def pay_balance(self, request, pk=None):
        member = self.get_object()
        logger.info(f"MemberViewSet.pay_balance: member_id={member.id} name={member.name} incoming amount_paid={request.data.get('amount_paid')}")
        s = BalancePaymentSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        payment = member.payments.filter(
            status__in=["partial","pending"]
        ).order_by("-paid_date").first()

        if not payment:
            logger.warning(f"MemberViewSet.pay_balance: rejected — member_id={member.id} has no outstanding balance")
            return Response({"detail": "No outstanding balance."}, status=400)

        extra = Decimal(str(s.validated_data["amount_paid"]))
        if extra <= 0:
            logger.warning(f"MemberViewSet.pay_balance: rejected — member_id={member.id} amount={extra} must be > 0")
            return Response({"detail": "Amount must be > 0."}, status=400)
        if extra > payment.balance:
            logger.warning(f"MemberViewSet.pay_balance: rejected — member_id={member.id} amount={extra} exceeds balance={payment.balance}")
            return Response({
                "detail": f"Amount ₹{extra} exceeds balance of ₹{payment.balance}."
            }, status=400)

        installment = _create_installment(
            payment, member, extra, "balance",
            notes=s.validated_data.get("notes", ""),
            mode_of_payment=s.validated_data.get("mode_of_payment", "cash"),
        )
        _record_income_for_installment(member, payment, installment)

        payment.refresh_from_db()
        bill_data = _build_bill(member, payment, _gym_info())

        try:
            from apps.notifications.whatsapp import send_bill_on_whatsapp
            phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
            if phone and not phone.startswith("91"):
                phone = f"91{phone}"
            send_bill_on_whatsapp(phone, bill_data, "balance")
        except Exception as e:
            logger.warning(f"Bill WhatsApp send failed for balance payment: member_id={member.id} error={e}")

        return Response({
            **MemberPaymentSerializer(payment).data,
            "bill": bill_data,
        })

    @action(detail=True, methods=["post"], url_path="upgrade-diet")
    def upgrade_diet(self, request, pk=None):
        """
        Called when a standard member is upgraded to premium (diet only added).
        Updates latest payment to include diet fee, records installment if amount_paid > 0.
        Does NOT create a new TrainerAssignment — use this instead of assign-trainer for
        standard→premium upgrades where PT was already assigned.
        """
        from apps.finances.gst_utils import get_diet_plan_amount as _get_diet_amt
        member = self.get_object()
        logger.info(f"MemberViewSet.upgrade_diet: member_id={member.id} name={member.name} amount_paid={request.data.get('amount_paid')}")

        latest_payment = member.payments.select_related("plan").order_by("-created_at").first()
        if not latest_payment:
            logger.warning(f"MemberViewSet.upgrade_diet: rejected — member_id={member.id} has no payment record")
            return Response({"detail": "No payment record found for this member."}, status=400)

        diet_amt_full = _get_diet_amt()
        if diet_amt_full <= 0:
            logger.warning(f"MemberViewSet.upgrade_diet: rejected — member_id={member.id} diet plan amount not configured")
            return Response({"detail": "Diet plan amount is not configured in settings."}, status=400)

        # Prorate diet by pending days in membership (capped at 30), same logic as PT
        today = timezone.localdate()
        if member.renewal_date and member.renewal_date > today:
            diet_days = min(30, (member.renewal_date - today).days)
            diet_amt = (diet_amt_full / 30 * diet_days).quantize(Decimal("0.01"), ROUND_HALF_UP) if diet_days < 30 else diet_amt_full
        else:
            diet_amt = diet_amt_full

        if latest_payment.diet_plan_amount >= diet_amt:
            logger.warning(
                f"MemberViewSet.upgrade_diet: rejected — member_id={member.id} diet fee already included "
                f"(existing={latest_payment.diet_plan_amount} >= new={diet_amt})"
            )
            return Response({"detail": "Diet plan fee already included in this payment cycle."}, status=400)

        # Re-derive existing PT fee from:
        #   plan_price = plan.base - discount + PT + previous_diet
        #   → PT = plan_price - plan.base + discount - previous_diet
        plan_base_price = latest_payment.plan.price if latest_payment.plan else Decimal("0")
        discount_amt    = latest_payment.discount_amount
        existing_pt_fee = max(
            Decimal("0"),
            latest_payment.plan_price - plan_base_price + discount_amt - latest_payment.diet_plan_amount
        )
        logger.info(
            f"MemberViewSet.upgrade_diet: pricing inputs — member_id={member.id} diet_amt_full={diet_amt_full} "
            f"prorated_diet_amt={diet_amt} plan_base_price={plan_base_price} discount_amt={discount_amt} "
            f"derived_existing_pt_fee={existing_pt_fee}"
        )

        base, gst_amt, total, rate = _calc_gst(plan_base_price - discount_amt + existing_pt_fee + diet_amt)
        latest_payment.plan_price       = base
        latest_payment.diet_plan_amount = diet_amt
        latest_payment.gst_rate         = rate
        latest_payment.gst_amount       = gst_amt
        latest_payment.total_with_gst   = total
        latest_payment.save()

        amount_paid = Decimal(str(request.data.get("amount_paid", 0)))
        if amount_paid > 0:
            installment = _create_installment(
                latest_payment, member, amount_paid, "balance",
                notes=request.data.get("notes", ""),
                mode_of_payment=request.data.get("mode_of_payment", "cash"),
            )
            _record_income_for_installment(member, latest_payment, installment)

        latest_payment.refresh_from_db()
        bill_data = _build_bill(member, latest_payment, _gym_info())
        bill_data["is_diet_upgrade"] = True   # hint for frontend to show only diet row

        return Response({
            **MemberPaymentSerializer(latest_payment).data,
            "bill": bill_data,
        })

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        member = self.get_object()
        member.status = "cancelled"
        reason = request.data.get("reason","")
        if reason:
            member.notes = reason + "\n" + member.notes
        member.save()
        logger.info(f"MemberViewSet.cancel: member_id={member.id} name={member.name} cancelled, reason={reason!r}")
        return Response({"detail": "Member cancelled"})

    @action(detail=False, methods=["get"])
    def expiring_soon(self, request):
        days   = int(request.query_params.get("days", 7))
        cutoff = timezone.localdate() + timedelta(days=days)
        qs = Member.objects.select_related("plan", "diet").prefetch_related(
            Prefetch(
                "payments",
                queryset=MemberPayment.objects.order_by("-created_at"),
                to_attr="prefetched_payments",
            ),
        ).filter(
            status="active",
            renewal_date__lte=cutoff,
            renewal_date__gte=timezone.localdate()
        )
        return Response(MemberSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        _auto_expire_members()
        today = timezone.localdate()
        # Single aggregate query with conditional counts instead of 6 separate .count() queries.
        agg = Member.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(status="active")),
            expired=Count("id", filter=Q(status="expired")),
            cancelled=Count("id", filter=Q(status="cancelled")),
            expiring_7=Count("id", filter=Q(
                status="active",
                renewal_date__lte=today + timedelta(days=7),
                renewal_date__gte=today,
            )),
            new_this_month=Count("id", filter=Q(
                join_date__year=today.year,
                join_date__month=today.month,
            )),
        )
        return Response(agg)


class MemberPaymentViewSet(viewsets.ModelViewSet):
    queryset         = MemberPayment.objects.select_related("member","plan").prefetch_related("installment_payments").all()
    serializer_class = MemberPaymentSerializer
    filterset_fields = ["member","status"]
    ordering_fields  = ["paid_date"]

class MemberAttendanceViewSet(viewsets.ModelViewSet):
    queryset         = MemberAttendance.objects.select_related("member").all()
    serializer_class = MemberAttendanceSerializer
    filterset_fields = {
        "member": ["exact"],
        "date":   ["exact", "year", "month"],
    }
    ordering_fields  = ["date","check_in"]

    def list(self, request, *args, **kwargs):
        try:
            from apps.staff.views import _auto_mark_absent_members
            _auto_mark_absent_members()
        except Exception:
            logger.exception("MemberAttendanceViewSet.list: _auto_mark_absent_members failed")
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def today(self, request):
        qs = MemberAttendance.objects.filter(
            date=timezone.localdate()).select_related("member")
        return Response(MemberAttendanceSerializer(qs, many=True).data)


# ─── Public kiosk endpoints (no auth) ────────────────

class KioskLookupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw = str(request.data.get("id_input","")).strip().upper()
        if not raw:
            return Response({"detail":"Enter an ID."}, status=400)

        if raw.startswith("M"):
            try:
                member = Member.objects.select_related("plan").get(pk=int(raw[1:]))
                return Response({
                    "type":"member", "id":member.id,
                    "display_id": member.display_id(),
                    "name": member.name, "role":"Member",
                    "plan": member.plan.name if member.plan else "No Plan",
                    "status": member.status,
                    "renewal": str(member.renewal_date) if member.renewal_date else None,
                    "photo": member.photo_url or "",
                })
            except (ValueError, Member.DoesNotExist):
                return Response({"detail":f"No member found with ID {raw}."}, status=404)

        elif raw.startswith("S"):
            from apps.staff.models import StaffMember
            try:
                staff = StaffMember.objects.get(pk=int(raw[1:]))
                return Response({
                    "type":"staff", "id":staff.id,
                    "display_id": f"S{staff.id:04d}",
                    "name": staff.name,
                    "role": staff.role.capitalize(),
                    "shift": staff.shift, "status": staff.status,
                    "photo": staff.photo_url or "",
                })
            except (ValueError, StaffMember.DoesNotExist):
                return Response({"detail":f"No staff found with ID {raw}."}, status=404)

        return Response({"detail":"ID must start with M (member) or S (staff)."}, status=400)


class KioskMarkAttendanceView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ptype = request.data.get("type")
        pid   = request.data.get("id")
        now   = timezone.now()
        today = timezone.localdate()

        # ── KEY FIX: convert UTC→IST before extracting time ──
        local_now  = timezone.localtime(now)
        local_time = local_now.time()           # IST time e.g. 09:17, not 03:47

        if ptype == "member":
            try:
                member   = Member.objects.get(pk=pid)
                existing = MemberAttendance.objects.filter(member=member, date=today).first()
                if existing and not existing.check_out:
                    existing.check_out = local_time
                    existing.save()
                    act = "check_out"
                elif existing:
                    MemberAttendance.objects.create(
                        member=member, date=today, check_in=local_time
                    )
                    act = "check_in"
                else:
                    MemberAttendance.objects.create(
                        member=member, date=today, check_in=local_time
                    )
                    act = "check_in"
                logger.info(f"KioskMarkAttendanceView: member_id={member.id} name={member.name} action={act} time={local_time}")
                return Response({
                    "action": act, "name": member.name,
                    "time":   local_now.strftime("%I:%M %p"),   # display IST
                    "date":   str(today), "type": "member",
                })
            except Member.DoesNotExist:
                logger.warning(f"KioskMarkAttendanceView: member not found for id={pid}")
                return Response({"detail": "Member not found."}, status=404)

        # ── PATCH: apps/members/views.py — KioskMarkAttendanceView ──────────────────
# Replace the entire `elif ptype == "staff":` block with this version.
# Change: block re-login if staff has already checked out today.
# ─────────────────────────────────────────────────────────────────────────────

        elif ptype == "staff":
            from apps.staff.models import StaffMember, StaffAttendance
            try:
                staff    = StaffMember.objects.get(pk=pid)
                existing = StaffAttendance.objects.filter(staff=staff, date=today).first()

                if existing and existing.check_out:
                    # ── Already checked out — block re-entry ──────────────
                    return Response({
                        "action":  "already_out",
                        "name":    staff.name,
                        "message": (
                            f"Already checked out at "
                            f"{existing.check_out.strftime('%I:%M %p')}."
                            f" No re-entry allowed for today."
                        ),
                        "time":  existing.check_out.strftime("%I:%M %p"),
                        "date":  str(today),
                        "type":  "staff",
                    }, status=200)

                elif existing and not existing.check_out:
                    # ── Checked in, not yet out → mark check-out ─────────
                    existing.check_out = local_time
                    existing.save()
                    act = "check_out"

                else:
                    # ── No record yet → first check-in ───────────────────
                    StaffAttendance.objects.create(
                        staff=staff, date=today,
                        check_in=local_time, status="present"
                    )
                    act = "check_in"

                logger.info(f"KioskMarkAttendanceView: staff_id={staff.id} name={staff.name} action={act} time={local_time}")
                return Response({
                    "action": act,
                    "name":   staff.name,
                    "time":   local_now.strftime("%I:%M %p"),
                    "date":   str(today),
                    "type":   "staff",
                })

            except StaffMember.DoesNotExist:
                logger.warning(f"KioskMarkAttendanceView: staff not found for id={pid}")
                return Response({"detail": "Staff not found."}, status=404)
    
class DietPlanViewSet(viewsets.ModelViewSet):
    queryset = DietPlan.objects.prefetch_related("items").all()
    serializer_class = DietPlanSerializer

    def _save_items(self, plan, items):
        for item in items:
            Diet.objects.create(
                plan=plan,
                food=item.get("food", ""),
                time=item.get("time"),
                quantity=item.get("quantity", 1),
                unit=item.get("unit", "g"),
                calories=item.get("calories", 0),
                notes=item.get("notes", ""),
            )

    def create(self, request, *args, **kwargs):
        items = request.data.get("items", [])
        plan = DietPlan.objects.create(
            name=request.data.get("name", "Unnamed Plan"),
            foodType=request.data.get("foodType", "veg"),
        )
        self._save_items(plan, items)
        logger.info(f"DietPlanViewSet.create: diet plan id={plan.id} name={plan.name} items_count={len(items)}")
        return Response(DietPlanSerializer(plan).data, status=201)

    def update(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.name = request.data.get("name", plan.name)
        plan.foodType = request.data.get("foodType", plan.foodType)
        plan.save()
        plan.items.all().delete()
        items = request.data.get("items", [])
        self._save_items(plan, items)
        logger.info(f"DietPlanViewSet.update: diet plan id={plan.id} name={plan.name} items_count={len(items)}")
        return Response(DietPlanSerializer(plan).data)


class DietViewSet(viewsets.ModelViewSet):
    queryset = Diet.objects.all()
    serializer_class = DietSerializer


class MemberTrainerAssignmentViewSet(viewsets.ModelViewSet):
    queryset         = TrainerAssignment.objects.select_related("member", "trainer", "plan").all()
    serializer_class = TrainerAssignmentSerializer
    search_fields     = ["member__name", "trainer__name"]

    def get_queryset(self):
        qs = (
            TrainerAssignment.objects
            .select_related("member", "trainer", "plan")
            .prefetch_related(
                Prefetch(
                    "member__payments",
                    queryset=MemberPayment.objects.order_by("-created_at"),
                    to_attr="prefetched_payments",
                ),
                "pt_renewals",
            )
            .all()
        )
        params = self.request.query_params
        if params.get("member"):
            qs = qs.filter(member_id=params["member"])
        if params.get("trainer"):
            qs = qs.filter(trainer_id=params["trainer"])
        if params.get("plan"):
            qs = qs.filter(plan_id=params["plan"])
        return qs

    @staticmethod
    def _check_plan_eligibility(member):
        """Returns (ok, error_msg). A member needs standard/premium plan_type and must have opted in for personal trainer."""
        if not member.plan:
            return False, "Member has no membership plan. Assign a Standard or Premium plan first."
        if member.plan_type not in ("standard", "premium"):
            return False, (
                f"Personal trainer is only available for Standard and Premium plans. "
                f"This member is on the '{member.plan_type}' plan."
            )
        if not member.personal_trainer:
            return False, (
                f"This member has not opted for Personal Trainer. "
                f"Enable the Personal Trainer option on the member's profile first."
            )
        return True, None

    def create(self, request, *args, **kwargs):
        from apps.staff.models import StaffMember
        from django.core.exceptions import ValidationError as DjValidationError
        data = request.data
        logger.info(f"MemberTrainerAssignmentViewSet.create: incoming member_id={data.get('member')} trainer_id={data.get('trainer')} plan_id={data.get('plan')} amount_paid={data.get('amount_paid')}")

        try:
            member  = Member.objects.select_related("plan").get(pk=data.get("member"))
            trainer = StaffMember.objects.get(pk=data.get("trainer"), role="trainer")
        except Member.DoesNotExist:
            logger.warning(f"MemberTrainerAssignmentViewSet.create: rejected — member not found id={data.get('member')}")
            return Response({"detail": "Member not found."}, status=400)
        except StaffMember.DoesNotExist:
            logger.warning(f"MemberTrainerAssignmentViewSet.create: rejected — trainer not found id={data.get('trainer')}")
            return Response({"detail": "Trainer not found or staff member is not a Trainer."}, status=400)

        ok, err = self._check_plan_eligibility(member)
        if not ok:
            logger.warning(f"MemberTrainerAssignmentViewSet.create: rejected — member_id={member.id} eligibility check failed: {err}")
            return Response({"detail": err}, status=400)

        plan = None
        if data.get("plan"):
            plan = MembershipPlan.objects.filter(pk=data["plan"]).first()

        # Set initial PT period (30 days from today, capped at plan end)
        today = timezone.localdate()
        pt_start = today
        if member.renewal_date and member.renewal_date > today:
            pt_end = min(today + timedelta(days=30), member.renewal_date)
        else:
            pt_end = today + timedelta(days=30)

        assignment = TrainerAssignment(
            member        = member,
            trainer       = trainer,
            plan          = plan,
            startingtime  = data.get("startingtime"),
            endingtime    = data.get("endingtime"),
            working_days  = data.get("working_days", "0,1,2,3,4,5,6"),
            pt_start_date = pt_start,
            pt_end_date   = pt_end,
        )
        try:
            assignment.full_clean()
        except DjValidationError as exc:
            logger.warning(f"MemberTrainerAssignmentViewSet.create: rejected — member_id={member.id} trainer_id={trainer.id} validation failed: {'; '.join(exc.messages)}")
            return Response({"detail": "; ".join(exc.messages)}, status=400)

        assignment.save()
        logger.info(f"MemberTrainerAssignmentViewSet.create: assignment created id={assignment.id} member_id={member.id} trainer_id={trainer.id} pt_start={pt_start} pt_end={pt_end}")

        latest_payment = member.payments.select_related("plan").order_by("-created_at").first()

        # Recompute latest payment to include trainer PT fee AND current diet (for upgrades)
        from apps.finances.gst_utils import get_diet_plan_amount as _get_diet_amt
        trainer_fee_full = Decimal(str(trainer.personal_trainer_amt or 0))

        # Prorate PT and diet fees by actual days assigned (same logic as PT renewal)
        pt_days = (pt_end - pt_start).days
        trainer_fee = (trainer_fee_full / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP) if pt_days < 30 else trainer_fee_full
        has_diet_fee = bool(member.diet) or member.plan_type in ("premium", "dietonly-standard")
        diet_full = _get_diet_amt() if has_diet_fee else Decimal("0")
        diet_amt_current = (diet_full / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP) if (has_diet_fee and pt_days < 30) else diet_full
        logger.info(
            f"MemberTrainerAssignmentViewSet.create: PT/diet proration — assignment_id={assignment.id} "
            f"trainer_fee_full={trainer_fee_full} pt_days={pt_days} -> trainer_fee={trainer_fee} "
            f"has_diet_fee={has_diet_fee} diet_full={diet_full} -> diet_amt_current={diet_amt_current}"
        )

        if latest_payment and latest_payment.plan:
            base, gst_amt, total, rate = _calc_gst(
                latest_payment.plan.price - latest_payment.discount_amount + trainer_fee + diet_amt_current
            )
            latest_payment.plan_price       = base
            latest_payment.diet_plan_amount = diet_amt_current
            latest_payment.gst_rate         = rate
            latest_payment.gst_amount       = gst_amt
            latest_payment.total_with_gst   = total
            latest_payment.save()

            amount_paid = Decimal(str(request.data.get("amount_paid", 0)))
            if amount_paid > 0:
                installment = _create_installment(
                    latest_payment, member, amount_paid, "enrollment",
                    notes=request.data.get("notes", ""),
                    mode_of_payment=request.data.get("mode_of_payment", "cash"),
                )
                _record_income_for_installment(member, latest_payment, installment)

        bill_data = None
        if latest_payment:
            latest_payment.refresh_from_db()
            bill_data = _build_bill(member, latest_payment, _gym_info())

        return Response({
            **TrainerAssignmentSerializer(assignment).data,
            "bill": bill_data,
        }, status=201)

    def update(self, request, *args, **kwargs):
        from apps.staff.models import StaffMember
        from django.core.exceptions import ValidationError as DjValidationError
        assignment = self.get_object()
        data       = request.data
        logger.info(f"MemberTrainerAssignmentViewSet.update: assignment_id={assignment.id} member_id={assignment.member_id} payload keys={list(data.keys())}")

        if data.get("trainer"):
            try:
                assignment.trainer = StaffMember.objects.get(pk=data["trainer"], role="trainer")
            except StaffMember.DoesNotExist:
                logger.warning(f"MemberTrainerAssignmentViewSet.update: rejected — trainer not found id={data.get('trainer')} for assignment_id={assignment.id}")
                return Response({"detail": "Trainer not found or staff member is not a Trainer."}, status=400)

        if data.get("plan"):
            assignment.plan = MembershipPlan.objects.filter(pk=data["plan"]).first()
        elif "plan" in data and data["plan"] is None:
            assignment.plan = None

        if data.get("startingtime"):
            assignment.startingtime = data["startingtime"]
        if data.get("endingtime"):
            assignment.endingtime = data["endingtime"]
        if data.get("working_days"):
            assignment.working_days = data["working_days"]

        # Allow admin to manually adjust PT period dates (for corrections / testing)
        if data.get("pt_start_date"):
            assignment.pt_start_date = data["pt_start_date"]
        if data.get("pt_end_date"):
            assignment.pt_end_date = data["pt_end_date"]

        try:
            assignment.full_clean()
        except DjValidationError as exc:
            logger.warning(f"MemberTrainerAssignmentViewSet.update: rejected — assignment_id={assignment.id} validation failed: {'; '.join(exc.messages)}")
            return Response({"detail": "; ".join(exc.messages)}, status=400)

        assignment.save()
        logger.info(f"MemberTrainerAssignmentViewSet.update: assignment_id={assignment.id} updated — pt_start={assignment.pt_start_date} pt_end={assignment.pt_end_date}")
        return Response(TrainerAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"], url_path="pay-trainer-fee")
    def pay_trainer_fee(self, request, pk=None):
        from apps.finances.models import Expenditure
        from apps.finances.gst_utils import get_pt_payable_percent
        assignment = self.get_object()
        logger.info(f"MemberTrainerAssignmentViewSet.pay_trainer_fee: assignment_id={assignment.id} member_id={assignment.member_id} trainer_id={assignment.trainer_id}")

        pt_amt = assignment.trainer.personal_trainer_amt
        if not pt_amt or pt_amt <= 0:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_trainer_fee: rejected — assignment_id={assignment.id} trainer has no PT fee configured")
            return Response({"detail": "This trainer has no PT fee configured."}, status=400)

        pt_payable_pct = get_pt_payable_percent()
        payable_amt    = (Decimal(str(pt_amt)) * pt_payable_pct / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        logger.info(f"MemberTrainerAssignmentViewSet.pay_trainer_fee: assignment_id={assignment.id} pt_amt={pt_amt} pt_payable_pct={pt_payable_pct}% -> payable_amt={payable_amt}")

        with transaction.atomic():
            updated = TrainerAssignment.objects.filter(
                pk=assignment.pk, trainer_fee_paid=False
            ).update(trainer_fee_paid=True)
            if not updated:
                logger.warning(f"MemberTrainerAssignmentViewSet.pay_trainer_fee: rejected — assignment_id={assignment.id} trainer fee already paid")
                return Response({"detail": "Trainer fee already paid for this member."}, status=400)

            Expenditure.objects.create(
                category    = "salary",
                description = f"PT Fee — {assignment.trainer.name} for {assignment.member.name}",
                amount      = payable_amt,
                date        = timezone.localdate(),
                vendor      = assignment.trainer.name,
                notes       = f"Trainer assignment ID: {assignment.id} | PT fee: ₹{pt_amt} × {pt_payable_pct}% = ₹{payable_amt} | Invoice: {assignment.member.payments.order_by('-created_at').values_list('invoice_number', flat=True).first() or ''}",
            )

        assignment.refresh_from_db()
        return Response(TrainerAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"], url_path="pay-pt-trainer-fee")
    def pay_pt_trainer_fee(self, request, pk=None):
        """
        Pays the trainer's share from all unpaid PT renewal periods in one go.

        If multiple PT renewals have accumulated without a trainer payout,
        this action sums them all and records a single Expenditure entry.
        The PT_PAYABLE_PERCENT setting determines the trainer's share of each
        renewal's base_amount — this is already stored on each PTRenewal record
        as trainer_payable_amount when the renewal was created.
        """
        from apps.finances.models import Expenditure
        assignment = self.get_object()
        logger.info(f"MemberTrainerAssignmentViewSet.pay_pt_trainer_fee: assignment_id={assignment.id} member_id={assignment.member_id} trainer_id={assignment.trainer_id}")

        unpaid_renewals = list(assignment.pt_renewals.filter(trainer_paid=False))
        if not unpaid_renewals:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_pt_trainer_fee: rejected — assignment_id={assignment.id} no pending PT renewal trainer payments")
            return Response({"detail": "No pending PT renewal trainer payments."}, status=400)

        total_payable = sum(r.trainer_payable_amount for r in unpaid_renewals)
        if total_payable <= 0:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_pt_trainer_fee: rejected — assignment_id={assignment.id} total_payable={total_payable} <= 0")
            return Response({"detail": "No trainer amount to pay."}, status=400)
        logger.info(f"MemberTrainerAssignmentViewSet.pay_pt_trainer_fee: assignment_id={assignment.id} {len(unpaid_renewals)} unpaid renewal(s) -> total_payable={total_payable}")

        today     = timezone.localdate()
        trainer   = assignment.trainer
        member    = assignment.member
        inv_refs  = ", ".join(r.invoice_number for r in unpaid_renewals if r.invoice_number)
        periods   = ", ".join(f"{r.pt_start_date}→{r.pt_end_date}" for r in unpaid_renewals)

        Expenditure.objects.create(
            category    = "salary",
            description = f"PT Renewal Fee — {trainer.name} for {member.name}",
            amount      = total_payable,
            date        = today,
            vendor      = trainer.name,
            notes       = (
                f"PT renewal trainer payout | {len(unpaid_renewals)} period(s): {periods} "
                f"| Invoices: {inv_refs} "
                f"| Assignment ID: {assignment.id}"
            ),
        )

        # Mark all unpaid renewals as trainer_paid
        for r in unpaid_renewals:
            r.trainer_paid = True
            r.save()

        return Response(TrainerAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"], url_path="pay-pt-balance")
    def pay_pt_balance(self, request, pk=None):
        """
        Pay the outstanding balance on the latest partial/pending PTRenewal.
        Records an Income entry and updates the PTRenewal status.
        """
        from apps.finances.models import Income
        assignment = self.get_object()
        member     = assignment.member
        today      = timezone.localdate()
        logger.info(f"MemberTrainerAssignmentViewSet.pay_pt_balance: assignment_id={assignment.id} member_id={member.id} incoming amount_paid={request.data.get('amount_paid')}")

        renewal = assignment.pt_renewals.filter(
            status__in=["partial", "pending"]
        ).order_by("-created_at").first()

        if not renewal:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_pt_balance: rejected — assignment_id={assignment.id} no pending PT balance found")
            return Response({"detail": "No pending PT balance found."}, status=400)

        balance = renewal.total_amount - renewal.amount_paid
        if balance <= 0:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_pt_balance: rejected — assignment_id={assignment.id} renewal_id={renewal.id} no balance remaining")
            return Response({"detail": "No balance remaining on this PT renewal."}, status=400)

        amount_paid     = Decimal(str(request.data.get("amount_paid", 0)))
        mode_of_payment = request.data.get("mode_of_payment", "cash")
        notes           = request.data.get("notes", "")

        if amount_paid <= 0:
            logger.warning(f"MemberTrainerAssignmentViewSet.pay_pt_balance: rejected — assignment_id={assignment.id} amount_paid={amount_paid} must be > 0")
            return Response({"detail": "amount_paid must be greater than 0."}, status=400)

        amount_paid = min(amount_paid, balance)

        # Update PTRenewal
        renewal.amount_paid += amount_paid
        new_balance = renewal.total_amount - renewal.amount_paid
        renewal.status = "paid" if new_balance <= Decimal("0.01") else "partial"
        renewal.save()
        logger.info(
            f"MemberTrainerAssignmentViewSet.pay_pt_balance: renewal_id={renewal.id} member_id={member.id} "
            f"pre_balance={balance} amount_paid_now={amount_paid} -> new_amount_paid={renewal.amount_paid} "
            f"new_balance={new_balance} status={renewal.status}"
        )

        # GST-first allocation for the balance payment
        gst_collected = Income.objects.filter(invoice_number=renewal.invoice_number).aggregate(
            t=Sum("gst_amount")
        )["t"] or Decimal("0")
        gst_remaining = max(renewal.gst_amount - gst_collected, Decimal("0"))
        gst_now  = min(amount_paid, gst_remaining).quantize(Decimal("0.01"), ROUND_HALF_UP)
        base_now = (amount_paid - gst_now).quantize(Decimal("0.01"), ROUND_HALF_UP)
        eff_rate = Decimal(str(renewal.gst_rate)) if gst_now > 0 else Decimal("0")
        logger.info(
            f"MemberTrainerAssignmentViewSet.pay_pt_balance: GST-first allocation — renewal_id={renewal.id} "
            f"renewal.gst_amount={renewal.gst_amount} gst_collected_so_far={gst_collected} "
            f"gst_remaining={gst_remaining} -> gst_now={gst_now} base_now={base_now} eff_rate={eff_rate}%"
        )

        Income.objects.create(
            source         = f"PT Renewal (Balance) — {member.name}",
            category       = "personal_training",
            base_amount    = base_now,
            gst_rate       = eff_rate,
            gst_amount     = gst_now,
            amount         = amount_paid,
            date           = today,
            member_id      = member.id,
            invoice_number = renewal.invoice_number,
            notes          = (
                f"PT Renewal Balance | {renewal.pt_start_date} → {renewal.pt_end_date} "
                f"| plan_total:{renewal.total_amount} "
                f"| mode:{mode_of_payment} "
                f"| Trainer: {assignment.trainer.name}"
                + (f" | {notes}" if notes else "")
            ),
        )

        # ── Send updated PT bill on WhatsApp ─────────────────────────────────
        from apps.notifications.whatsapp import send_bill_on_whatsapp
        gym = _gym_info()
        trainer = assignment.trainer
        bill_data = {
            "invoice_number":  renewal.invoice_number,
            "bill_type":       "PT Renewal",
            "member_id":       member.display_id(),
            "member_name":     member.name,
            "phone":           member.phone,
            "email":           member.email,
            "trainer_name":    trainer.name,
            "trainer_id":      f"S{trainer.id:04d}",
            "plan_name":       member.plan.name if member.plan else "",
            "plan_valid_to":   str(member.renewal_date),
            "pt_start_date":   str(renewal.pt_start_date),
            "pt_end_date":     str(renewal.pt_end_date),
            "pt_days":         renewal.pt_days,
            "full_pt_days":    30,
            "base_amount":     float(renewal.base_amount),
            "gst_rate":        float(renewal.gst_rate),
            "gst_amount":      float(renewal.gst_amount),
            "total_amount":    float(renewal.total_amount),
            "amount_paid":     float(renewal.amount_paid),
            "balance":         float(max(renewal.total_amount - renewal.amount_paid, Decimal("0"))),
            "status":          renewal.status,
            "mode_of_payment": mode_of_payment,
            "date":            str(today),
            "gym_name":        gym["name"],
            "gym_address":     gym["address"],
            "gym_phone":       gym["phone"],
            "gym_email":       gym["email"],
            "gym_gstin":       gym["gstin"],
            "notes":           notes,
        }
        phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
        if phone and not phone.startswith("91"):
            phone = f"91{phone}"
        try:
            send_bill_on_whatsapp(phone, bill_data, "pt_balance")
        except Exception:
            logger.exception(f"MemberTrainerAssignmentViewSet.pay_pt_balance: WhatsApp bill send failed for member_id={member.id} renewal_id={renewal.id}")
            raise

        return Response(TrainerAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["get"], url_path="pt-renewal-preview")
    def pt_renewal_preview(self, request, pk=None):
        """
        Returns a preview of what a PT renewal would cost, without committing anything.
        Useful for showing the modal with correct amounts before the admin confirms.
        """
        assignment = self.get_object()
        member     = assignment.member
        trainer    = assignment.trainer
        today      = timezone.localdate()
        logger.info(f"MemberTrainerAssignmentViewSet.pt_renewal_preview: assignment_id={assignment.id} member_id={member.id}")

        if member.status != "active":
            logger.info(f"pt_renewal_preview: assignment_id={assignment.id} cannot renew — member status={member.status}")
            return Response({"can_renew": False, "reason": "Member plan is not active."})
        if not member.renewal_date or member.renewal_date <= today:
            logger.info(f"pt_renewal_preview: assignment_id={assignment.id} cannot renew — member plan expired (renewal_date={member.renewal_date})")
            return Response({"can_renew": False, "reason": "Member plan has expired. Renew the membership first."})
        if assignment.pt_end_date and assignment.pt_end_date >= member.renewal_date:
            logger.info(f"pt_renewal_preview: assignment_id={assignment.id} cannot renew — PT already covers plan expiry (pt_end={assignment.pt_end_date}, plan_end={member.renewal_date})")
            return Response({
                "can_renew": False,
                "reason": f"PT is already active until plan expiry ({member.renewal_date}). Extend the membership plan to unlock PT renewal.",
            })

        plan_days_remaining  = (member.renewal_date - today).days
        current_pt_remaining = (
            max(0, (assignment.pt_end_date - today).days)
            if assignment.pt_end_date else 0
        )
        # Charge only for the new gap being added (plan remaining minus already-covered days)
        pt_days = min(30, max(0, plan_days_remaining - current_pt_remaining))

        full_amt = Decimal(str(trainer.personal_trainer_amt or 0))
        if full_amt <= 0:
            logger.warning(f"pt_renewal_preview: assignment_id={assignment.id} trainer_id={trainer.id} has no PT fee configured")
            return Response({"can_renew": False, "reason": "Trainer has no PT fee configured."})

        base = (full_amt / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP)
        logger.info(
            f"pt_renewal_preview: assignment_id={assignment.id} plan_days_remaining={plan_days_remaining} "
            f"current_pt_remaining={current_pt_remaining} -> pt_days={pt_days} full_amt={full_amt} base={base}"
        )
        base_calc, gst_amt, total, rate = _calc_gst(base)

        # End date = today + paid days + bonus days already active, capped at plan expiry
        pt_end_preview = min(
            today + timedelta(days=pt_days + current_pt_remaining),
            member.renewal_date,
        )
        return Response({
            "can_renew":            True,
            "pt_days":              pt_days,
            "plan_days_remaining":  plan_days_remaining,
            "current_pt_remaining": current_pt_remaining,
            "pt_start_date":        str(today),
            "pt_end_date":          str(pt_end_preview),
            "base_amount":          float(base_calc),
            "gst_rate":             float(rate),
            "gst_amount":           float(gst_amt),
            "total_amount":         float(total),
            "member_name":          member.name,
            "member_id":            member.display_id(),
            "member_phone":         member.phone,
            "plan_name":            member.plan.name if member.plan else "",
            "plan_valid_to":        str(member.renewal_date),
            "trainer_name":         trainer.name,
        })

    @action(detail=True, methods=["post"], url_path="renew-pt")
    def renew_pt(self, request, pk=None):
        """
        Renews the PT period for this trainer assignment.

        Business rules:
        - Member plan must be active and not expired.
        - PT duration = min(30, days remaining in member plan from today).
        - PT amount is prorated: (trainer_pt_amt / 30) × pt_days + GST.
        - Creates a PTRenewal record and an Income entry.
        - Updates TrainerAssignment.pt_start_date / pt_end_date.
        - Returns bill data for download.
        """
        from apps.finances.models import Income
        assignment = self.get_object()
        member     = assignment.member
        trainer    = assignment.trainer
        today      = timezone.localdate()
        logger.info(f"MemberTrainerAssignmentViewSet.renew_pt: assignment_id={assignment.id} member_id={member.id} trainer_id={trainer.id} amount_paid={request.data.get('amount_paid')}")

        # ── Validation ───────────────────────────────────────────────────────
        if member.status != "active":
            logger.warning(f"renew_pt: rejected — assignment_id={assignment.id} member status={member.status} (not active)")
            return Response({"detail": "Member plan is not active. Renew membership first."}, status=400)

        if not member.renewal_date or member.renewal_date <= today:
            logger.warning(f"renew_pt: rejected — assignment_id={assignment.id} member plan expired (renewal_date={member.renewal_date})")
            return Response({"detail": "Member plan has expired. Renew the membership plan first."}, status=400)

        if assignment.pt_end_date and assignment.pt_end_date >= member.renewal_date:
            logger.warning(f"renew_pt: rejected — assignment_id={assignment.id} PT already covers plan expiry (pt_end={assignment.pt_end_date}, plan_end={member.renewal_date})")
            return Response({"detail": f"PT is already active until plan expiry ({member.renewal_date}). Extend the membership plan first."}, status=400)

        plan_days_remaining  = (member.renewal_date - today).days
        current_pt_remaining = (
            max(0, (assignment.pt_end_date - today).days)
            if assignment.pt_end_date else 0
        )
        # Charge only for the new days being added beyond current PT coverage
        pt_days = min(30, max(0, plan_days_remaining - current_pt_remaining))

        if pt_days <= 0:
            logger.warning(f"renew_pt: rejected — assignment_id={assignment.id} pt_days={pt_days} (no new PT days to renew)")
            return Response({"detail": "No new PT days to renew — PT already covers the remaining plan period."}, status=400)

        full_amt = Decimal(str(trainer.personal_trainer_amt or 0))
        if full_amt <= 0:
            logger.warning(f"renew_pt: rejected — assignment_id={assignment.id} trainer_id={trainer.id} has no PT fee configured")
            return Response({"detail": "Trainer has no PT fee configured."}, status=400)

        # ── Amount calculation (based on new days only) ───────────────────────
        base_for_days = (full_amt / 30 * pt_days).quantize(Decimal("0.01"), ROUND_HALF_UP)
        logger.info(
            f"renew_pt: assignment_id={assignment.id} plan_days_remaining={plan_days_remaining} "
            f"current_pt_remaining={current_pt_remaining} -> pt_days={pt_days} full_amt={full_amt} base_for_days={base_for_days}"
        )
        base, gst_amt, total, rate = _calc_gst(base_for_days)

        amount_paid     = Decimal(str(request.data.get("amount_paid", 0)))
        mode_of_payment = request.data.get("mode_of_payment", "cash")
        notes           = request.data.get("notes", "")
        pt_start        = today
        # New end = today + new days + bonus carry-over, capped at plan expiry
        pt_end = min(
            today + timedelta(days=pt_days + current_pt_remaining),
            member.renewal_date,
        )

        # ── Invoice number ────────────────────────────────────────────────────
        renewal_seq = assignment.pt_renewals.count() + 1
        inv_no = f"PT-{today.year}{today.month:02d}-M{member.id:04d}-{renewal_seq:02d}"

        # ── Determine status ──────────────────────────────────────────────────
        if amount_paid >= total:
            renewal_status = "paid"
        elif amount_paid > 0:
            renewal_status = "partial"
        else:
            renewal_status = "pending"

        # ── Trainer payable for this renewal ──────────────────────────────────
        from apps.finances.gst_utils import get_pt_payable_percent
        pt_payable_pct         = get_pt_payable_percent()
        trainer_payable_amount = (base * pt_payable_pct / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        logger.info(
            f"renew_pt: assignment_id={assignment.id} invoice={inv_no} amount_paid={amount_paid} total={total} "
            f"-> status={renewal_status} trainer_payable_amount = base({base}) * pt_payable_pct({pt_payable_pct}%) = {trainer_payable_amount}"
        )

        # ── Create PTRenewal record ───────────────────────────────────────────
        renewal = PTRenewal.objects.create(
            assignment             = assignment,
            member                 = member,
            trainer                = trainer,
            pt_start_date          = pt_start,
            pt_end_date            = pt_end,
            pt_days                = pt_days,
            base_amount            = base,
            gst_rate               = rate,
            gst_amount             = gst_amt,
            total_amount           = total,
            amount_paid            = amount_paid,
            mode_of_payment        = mode_of_payment,
            invoice_number         = inv_no,
            status                 = renewal_status,
            paid_date              = today,
            notes                  = notes,
            trainer_payable_amount = trainer_payable_amount,
            trainer_paid           = False,
        )

        logger.info(f"renew_pt: PTRenewal created id={renewal.id} invoice={inv_no} member_id={member.id} pt_start={pt_start} pt_end={pt_end} pt_days={pt_days} base={base} gst={gst_amt} total={total}")

        # ── Update assignment PT dates ────────────────────────────────────────
        assignment.pt_start_date = pt_start
        assignment.pt_end_date   = pt_end
        assignment.save()

        # ── Record Income entry ───────────────────────────────────────────────
        if amount_paid > 0:
            # GST-first allocation for this payment
            gst_remaining = gst_amt
            gst_now = min(amount_paid, gst_remaining).quantize(Decimal("0.01"), ROUND_HALF_UP)
            base_now = (amount_paid - gst_now).quantize(Decimal("0.01"), ROUND_HALF_UP)
            effective_rate = Decimal(str(rate)) if gst_now > 0 else Decimal("0")
            logger.info(
                f"renew_pt: Income allocation — renewal_id={renewal.id} amount_paid={amount_paid} "
                f"gst_amt={gst_amt} -> gst_now={gst_now} base_now={base_now} effective_rate={effective_rate}%"
            )

            Income.objects.create(
                source         = f"PT Renewal — {member.name}",
                category       = "personal_training",
                base_amount    = base_now,
                gst_rate       = effective_rate,
                gst_amount     = gst_now,
                amount         = amount_paid,
                date           = today,
                member_id      = member.id,
                invoice_number = inv_no,
                notes          = (
                    f"PT Renewal | {pt_start} → {pt_end} | {pt_days} days "
                    f"| plan_total:{total} "
                    f"| mode:{mode_of_payment} "
                    f"| Trainer: {trainer.name}"
                ),
            )

        # ── Build bill data ───────────────────────────────────────────────────
        gym      = _gym_info()
        bill_data = {
            "invoice_number":  inv_no,
            "bill_type":       "PT Renewal",
            "member_id":       member.display_id(),
            "member_name":     member.name,
            "phone":           member.phone,
            "email":           member.email,
            "trainer_name":    trainer.name,
            "trainer_id":      f"S{trainer.id:04d}",
            "plan_name":       member.plan.name if member.plan else "",
            "plan_valid_to":   str(member.renewal_date),
            "pt_start_date":   str(pt_start),
            "pt_end_date":     str(pt_end),
            "pt_days":         pt_days,
            "bonus_days":      current_pt_remaining,
            "full_pt_days":    30,
            "base_amount":     float(base),
            "gst_rate":        float(rate),
            "gst_amount":      float(gst_amt),
            "total_amount":    float(total),
            "amount_paid":     float(amount_paid),
            "balance":         float(max(total - amount_paid, Decimal("0"))),
            "status":          renewal_status,
            "mode_of_payment": mode_of_payment,
            "date":            str(today),
            "gym_name":        gym["name"],
            "gym_address":     gym["address"],
            "gym_phone":       gym["phone"],
            "gym_email":       gym["email"],
            "gym_gstin":       gym["gstin"],
            "notes":           notes,
        }

        # ── Send PT bill on WhatsApp ──────────────────────────────────────────
        from apps.notifications.whatsapp import send_bill_on_whatsapp
        phone = str(member.phone or "").strip().replace(" ", "").replace("-", "")
        if phone and not phone.startswith("91"):
            phone = f"91{phone}"
        try:
            send_bill_on_whatsapp(phone, bill_data, "pt_renewal")
        except Exception:
            logger.exception(f"renew_pt: WhatsApp bill send failed for member_id={member.id} renewal_id={renewal.id}")
            raise

        return Response({
            **TrainerAssignmentSerializer(assignment).data,
            "renewal":  PTRenewalSerializer(renewal).data,
            "bill":     bill_data,
        }, status=201)