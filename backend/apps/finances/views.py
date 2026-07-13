import logging
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum
from django.utils import timezone
import calendar
from .models import Income, Expenditure, GymSetting
from .serializers import IncomeSerializer, ExpenditureSerializer
from .gst_utils import get_gst_rate, get_gym_info

logger = logging.getLogger(__name__)


class IncomeViewSet(viewsets.ModelViewSet):
    queryset         = Income.objects.all()
    serializer_class = IncomeSerializer
    filterset_fields = ["category","date"]
    ordering_fields  = ["date","amount"]
    search_fields    = ["source","notes","invoice_number"]

    def perform_create(self, serializer):
        instance = serializer.save()
        logger.info(
            f"Income created: id={instance.id} source={instance.source} category={instance.category} "
            f"base_amount={instance.base_amount} gst_rate={instance.gst_rate} gst_amount={instance.gst_amount} "
            f"total_amount={instance.amount} date={instance.date} invoice_number={instance.invoice_number}"
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(
            f"Income updated: id={instance.id} base_amount={instance.base_amount} gst_amount={instance.gst_amount} "
            f"total_amount={instance.amount} date={instance.date} invoice_number={instance.invoice_number}"
        )

    def perform_destroy(self, instance):
        logger.info(
            f"Income deleted: id={instance.id} source={instance.source} total_amount={instance.amount} date={instance.date}"
        )
        instance.delete()


class ExpenditureViewSet(viewsets.ModelViewSet):
    queryset         = Expenditure.objects.all()
    serializer_class = ExpenditureSerializer
    filterset_fields = ["category","date"]
    ordering_fields  = ["date","amount"]
    search_fields    = ["description","vendor"]

    def perform_create(self, serializer):
        instance = serializer.save()
        logger.info(
            f"Expenditure created: id={instance.id} category={instance.category} amount={instance.amount} "
            f"date={instance.date} vendor={instance.vendor}"
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(
            f"Expenditure updated: id={instance.id} category={instance.category} amount={instance.amount} date={instance.date}"
        )

    def perform_destroy(self, instance):
        logger.info(
            f"Expenditure deleted: id={instance.id} category={instance.category} amount={instance.amount} date={instance.date}"
        )
        instance.delete()


class FinanceSummaryView(APIView):
    def get(self, request):
        today = timezone.localdate()
        year  = int(request.query_params.get("year",  today.year))
        month = int(request.query_params.get("month", today.month))
        logger.info(f"FinanceSummaryView.get: computing finance summary for year={year} month={month}")
        yearlyinc = Income.objects.filter(date__year=year)
        inc = Income.objects.filter(date__year=year, date__month=month)
        exp = Expenditure.objects.filter(date__year=year, date__month=month)
        total_income  = inc.aggregate(t=Sum("amount"))["t"] or 0
        total_gst     = inc.aggregate(t=Sum("gst_amount"))["t"] or 0
        total_base    = inc.aggregate(t=Sum("base_amount"))["t"] or 0
        total_expense = exp.aggregate(t=Sum("amount"))["t"] or 0
        all_base_income = Income.objects.aggregate(t=Sum("base_amount"))["t"] or 0
        all_expense     = Expenditure.objects.aggregate(t=Sum("amount"))["t"] or 0
        net_savings     = all_base_income - all_expense
        yearly_income  =  yearlyinc.aggregate(t=Sum("base_amount"))["t"] or 0
        logger.info(
            f"FinanceSummaryView: month totals year={year} month={month} total_income={total_income} "
            f"total_base_income={total_base} total_gst_collected={total_gst} total_expense={total_expense}"
        )
        logger.info(
            f"FinanceSummaryView: savings calc all_base_income={all_base_income} - all_expense={all_expense} "
            f"-> net_savings={net_savings}"
        )

        # 12-month trend
        monthly = []
        for i in range(11, -1, -1):
            m = month - i
            y = year
            while m <= 0:
                m += 12; y -= 1
            inc_m = Income.objects.filter(date__year=y, date__month=m).aggregate(t=Sum("amount"))["t"] or 0
            exp_m = Expenditure.objects.filter(date__year=y, date__month=m).aggregate(t=Sum("amount"))["t"] or 0
            monthly.append({
                "month":   f"{calendar.month_abbr[m]} {y}",
                "income":  float(inc_m),
                "expense": float(exp_m),
                "savings": float(inc_m - exp_m),
            })

        inc_by_cat = list(inc.values("category").annotate(total=Sum("amount")).order_by("-total"))
        exp_by_cat = list(exp.values("category").annotate(total=Sum("amount")).order_by("-total"))

        from apps.members.models import MemberPayment, PTRenewal
        from django.db.models import F, ExpressionWrapper, DecimalField as DjangoDecimalField
        membership_outstanding = MemberPayment.objects.filter(
            status__in=["partial", "pending"]
        ).aggregate(t=Sum("balance"))["t"] or 0

        pt_renewal_outstanding = PTRenewal.objects.filter(
            status__in=["partial", "pending"]
        ).annotate(
            bal=ExpressionWrapper(
                F("total_amount") - F("amount_paid"),
                output_field=DjangoDecimalField(),
            )
        ).aggregate(t=Sum("bal"))["t"] or 0
        # --- "To be collected" for the selected month ---
        # 1) Invoices created this month (their full plan value)
        mp_total = MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("total_with_gst"))["t"] or 0
        pt_total = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("total_amount"))["t"] or 0
        mp_base  = MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("plan_price"))["t"] or 0
        pt_base  = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("base_amount"))["t"] or 0
        mp_gst   = MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("gst_amount"))["t"] or 0
        pt_gst   = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("gst_amount"))["t"] or 0

        # 2) Carry forward pending balance from previous months' invoices
        import datetime as _dt
        from apps.members.models import InstallmentPayment
        first_of_month = _dt.date(year, month, 1)
        carryover_total = carryover_base = carryover_gst = 0

        try:
            # MemberPayments from before this month with pending balance
            for mp in MemberPayment.objects.filter(paid_date__lt=first_of_month):
                collected_before = float(mp.installment_payments.filter(
                    paid_date__lt=first_of_month
                ).aggregate(t=Sum("amount"))["t"] or 0)
                pending = float(mp.total_with_gst) - collected_before
                if pending > 0.01:
                    gst = float(mp.gst_amount)
                    pending_gst = max(gst - collected_before, 0)
                    pending_base = pending - pending_gst
                    carryover_total += pending
                    carryover_base += pending_base
                    carryover_gst += pending_gst

            # PTRenewals from before this month with pending balance
            for ptr in PTRenewal.objects.filter(paid_date__lt=first_of_month):
                if not ptr.invoice_number:
                    continue
                collected_before = float(Income.objects.filter(
                    invoice_number=ptr.invoice_number, date__lt=first_of_month
                ).aggregate(t=Sum("amount"))["t"] or 0)
                pending = float(ptr.total_amount) - collected_before
                if pending > 0.01:
                    gst = float(ptr.gst_amount)
                    pending_gst = max(gst - collected_before, 0)
                    pending_base = pending - pending_gst
                    carryover_total += pending
                    carryover_base += pending_base
                    carryover_gst += pending_gst
        except Exception:
            logger.exception(
                f"FinanceSummaryView: error computing carryover pending balances for year={year} month={month}"
            )
            raise

        total_income_to_collect = float(mp_total) + float(pt_total) + carryover_total
        total_base_income_to_collect = float(mp_base) + float(pt_base) + carryover_base
        total_gst_to_collect = float(mp_gst) + float(pt_gst) + carryover_gst
        logger.info(
            f"FinanceSummaryView: to-collect totals year={year} month={month} "
            f"total_income_to_collect={total_income_to_collect} total_base_income_to_collect={total_base_income_to_collect} "
            f"total_gst_to_collect={total_gst_to_collect} carryover_total={carryover_total}"
        )

        outstanding = membership_outstanding + pt_renewal_outstanding
        logger.info(
            f"FinanceSummaryView: outstanding_balance={outstanding} "
            f"membership_outstanding={membership_outstanding} pt_renewal_outstanding={pt_renewal_outstanding}"
        )
        return Response({
            "month": month, "year": year,
            "total_income":         float(total_income),
            "total_base_income":    float(total_base),
            "total_gst_collected":  float(total_gst),
            "total_expense":        float(total_expense),
            "net_savings":          float(net_savings),
            "outstanding_balance":  float(outstanding),
            "pt_renewal_outstanding": float(pt_renewal_outstanding),
            "membership_outstanding": float(membership_outstanding),
            "monthly_trend":        monthly,
            "income_by_category":   inc_by_cat,
            "expense_by_category":  exp_by_cat,
            "yearly_income":        float(yearly_income),
            "total_income_to_collect": float(total_income_to_collect),
            "total_base_income_to_collect": float(total_base_income_to_collect),
            "total_gst_to_collect": float(total_gst_to_collect),
        })


class MonthlyReportView(APIView):
    """Returns full detail for GST report — all transactions for the month."""
    def get(self, request):
        from collections import defaultdict
        from decimal import Decimal

        today = timezone.localdate()
        year  = int(request.query_params.get("year",  today.year))
        month = int(request.query_params.get("month", today.month))
        logger.info(f"MonthlyReportView.get: generating GST/monthly report for year={year} month={month}")

        incomes  = Income.objects.filter(date__year=year, date__month=month).order_by("date")
        expenses = Expenditure.objects.filter(date__year=year, date__month=month).order_by("date")

        total_income   = incomes.aggregate(t=Sum("amount"))["t"]     or 0
        total_expense  = expenses.aggregate(t=Sum("amount"))["t"]    or 0
        total_gst      = incomes.aggregate(t=Sum("gst_amount"))["t"] or 0

        total_income_without_gst = total_income - total_gst
        logger.info(
            f"MonthlyReportView: raw aggregates year={year} month={month} total_income={total_income} "
            f"total_gst(raw_aggregate)={total_gst} total_expense={total_expense} "
            f"total_income_without_gst={total_income_without_gst}"
        )

        gym = get_gym_info()

        def _parse_note_field(notes, key):
            if not notes:
                return None
            for part in notes.split("|"):
                part = part.strip()
                if part.startswith(f"{key}:"):
                    return part.split(":", 1)[1].strip()
            return None

        # ── Group incomes by invoice_number ──────────────────────────────────
        # Enrollment + balance-payment rows share the same invoice number.
        # Merge them into one row showing the full plan totals.
        invoice_groups = defaultdict(list)
        standalone     = []

        for income in incomes:
            if income.invoice_number:
                invoice_groups[income.invoice_number].append(income)
            else:
                standalone.append(income)

        # ── Load MemberPayments as source of truth for plan totals ────────────
        # The Income.notes plan_total is written at enrollment time and goes stale
        # when a trainer assignment later updates the payment (adds PT fee).
        # MemberPayment.total_with_gst is always up-to-date.
        from apps.members.models import MemberPayment as _MemberPayment,PTRenewal
        inv_nos = [i.invoice_number for i in incomes if i.invoice_number]
        payments_by_inv = {
            mp.invoice_number: mp
            for mp in _MemberPayment.objects.filter(invoice_number__in=inv_nos)
            
        }

        merged_incomes = []
        for income in incomes:
            mp = payments_by_inv.get(income.invoice_number) if income.invoice_number else None
            rate        = Decimal(str(income.gst_rate or 0))
            amount      = Decimal(str(income.amount))
            base_amount = Decimal(str(income.base_amount))
            gst_amount  = Decimal(str(income.gst_amount))
            
            pt_str = _parse_note_field(income.notes, "plan_total")
            plan_total = Decimal(str(pt_str)) if pt_str else (base_amount+gst_amount)
            if mp:
                plan_total = Decimal(str(mp.total_with_gst))

            merged_incomes.append({
                "id":             income.id,
                "date":           str(income.date),
                "invoice_number": income.invoice_number,
                "source":         income.source,
                "category":       income.category,
                "base_amount":    float(base_amount),
                "gst_rate":       float(rate),
                "gst_amount":     float(gst_amount),
                "plan_total":     float(plan_total),
                "amount":         float(amount),
                "mode_of_payment": _parse_note_field(income.notes,"mode") or "cash" ,
            })

        

        # for income in standalone:
        #     pt_str = _parse_note_field(income.notes, "plan_total")
        #     plan_total = float(pt_str) if pt_str else float(income.base_amount + income.gst_amount)
        #     merged_incomes.append({
        #         "id":             income.id,
        #         "date":           str(income.date),
        #         "invoice_number": income.invoice_number,
        #         "source":         income.source,
        #         "category":       income.category,
        #         "base_amount":    float(income.base_amount),
        #         "gst_rate":       float(income.gst_rate),
        #         "gst_amount":     float(income.gst_amount),
        #         "plan_total":     plan_total,
        #         "amount":         float(income.amount),
        #         "mode_of_payment": _parse_note_field(income.notes, "mode") or "cash",
        #     })

        merged_incomes.sort(key=lambda x: x["date"])

        # Summary totals derived from merged rows (plan-level, not installment-level)
        total_base = sum(r["base_amount"] for r in merged_incomes)
        total_gst  = sum(r["gst_amount"]  for r in merged_incomes)
        logger.info(
            f"MonthlyReportView: merged-row totals year={year} month={month} total_base={total_base} "
            f"total_gst(merged)={total_gst} merged_income_rows={len(merged_incomes)}"
        )

        # --- "To be collected" for the selected month ---
        # 1) Invoices created this month
        membership_income_to_collect = _MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("total_with_gst"))["t"] or 0
        personal_trainer_income_to_collect = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("total_amount"))["t"] or 0

        membership_base_income_to_collect = _MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("plan_price"))["t"] or 0
        personal_trainer_base_income_to_collect = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("base_amount"))["t"] or 0

        membership_gst_to_collect = _MemberPayment.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("gst_amount"))["t"] or 0
        personal_trainer_gst_to_collect = PTRenewal.objects.filter(paid_date__year=year, paid_date__month=month).aggregate(t=Sum("gst_amount"))["t"] or 0

        # 2) Carry forward pending balance from previous months' invoices
        import datetime as _dt
        from apps.members.models import InstallmentPayment as _InstallmentPayment
        first_of_month = _dt.date(year, month, 1)
        carryover_total = carryover_base = carryover_gst = 0

        try:
            for mp in _MemberPayment.objects.filter(paid_date__lt=first_of_month):
                collected_before = float(mp.installment_payments.filter(
                    paid_date__lt=first_of_month
                ).aggregate(t=Sum("amount"))["t"] or 0)
                pending = float(mp.total_with_gst) - collected_before
                if pending > 0.01:
                    gst = float(mp.gst_amount)
                    # GST is paid first; determine how much base & GST are still pending
                    pending_gst = max(gst - collected_before, 0)
                    pending_base = pending - pending_gst
                    carryover_total += pending
                    carryover_base += pending_base
                    carryover_gst += pending_gst

            for ptr in PTRenewal.objects.filter(paid_date__lt=first_of_month):
                if not ptr.invoice_number:
                    continue
                collected_before = float(Income.objects.filter(
                    invoice_number=ptr.invoice_number, date__lt=first_of_month
                ).aggregate(t=Sum("amount"))["t"] or 0)
                pending = float(ptr.total_amount) - collected_before
                if pending > 0.01:
                    gst = float(ptr.gst_amount)
                    # GST is paid first; determine how much base & GST are still pending
                    pending_gst = max(gst - collected_before, 0)
                    pending_base = pending - pending_gst
                    carryover_total += pending
                    carryover_base += pending_base
                    carryover_gst += pending_gst
        except Exception:
            logger.exception(
                f"MonthlyReportView: error computing carryover pending balances for year={year} month={month}"
            )
            raise

        total_income_to_collect = float(membership_income_to_collect) + float(personal_trainer_income_to_collect) + carryover_total
        total_base_income_to_collect = float(membership_base_income_to_collect) + float(personal_trainer_base_income_to_collect) + carryover_base
        total_gst_to_collect = float(membership_gst_to_collect) + float(personal_trainer_gst_to_collect) + carryover_gst
        logger.info(
            f"MonthlyReportView: to-collect totals year={year} month={month} "
            f"total_income_to_collect={total_income_to_collect} total_base_income_to_collect={total_base_income_to_collect} "
            f"total_gst_to_collect={total_gst_to_collect} carryover_total={carryover_total}"
        )
        logger.info(
            f"MonthlyReportView: final report totals year={year} month={month} "
            f"total_income_collected={total_income} total_base={total_base} total_gst_collected={total_gst} "
            f"total_expense={total_expense} net={total_income - total_expense}"
        )
        return Response({
            "gym":           gym,
            "month":         month,
            "year":          year,
            "month_name":    calendar.month_name[month],
            "total_income_collected":  float(total_income),
            "total_base":    total_base,
            "total_gst_collected":     total_gst,
            "total_expense": float(total_expense),
            "net":           float(total_income - total_expense),
            "incomes":       merged_incomes,
            "expenses":      ExpenditureSerializer(expenses, many=True).data,
            "total_income_without_gst": float(total_income_without_gst),
            "total_income_to_collect": float(total_income_to_collect),
            "total_base_income_to_collect": float(total_base_income_to_collect),
            "total_gst_to_collect": float(total_gst_to_collect),
        })


class GSTRateView(APIView):
    def get(self, request):
        rate = get_gst_rate()
        logger.info(f"GSTRateView.get: returning gst_rate={float(rate)}")
        return Response({"gst_rate": float(rate)})


class GymSettingsView(APIView):
    def get(self, request):
        logger.info("GymSettingsView.get: fetching all gym settings")
        return Response({s.key: s.value for s in GymSetting.objects.all()})

    def patch(self, request):
        logger.info(f"GymSettingsView.patch: updating settings keys={list(request.data.keys())}")
        for key, value in request.data.items():
            GymSetting.objects.update_or_create(key=key, defaults={"value": str(value)})
        return Response({s.key: s.value for s in GymSetting.objects.all()})
    
class ToBuyView(APIView):
    def _serialize(self, item):
        return {
            "id": item.id,
            "item_name": item.item_name,
            "quantity": item.quantity,
            "price": float(item.price) if item.price else None,
            "BuyingDate": item.BuyingDate,
            "Priority": item.Priority,
            "status": item.status,
            "notes": item.notes,
            "created_at": item.created_at,
            "item_url": item.item_url,
        }
    
    def get(self, request):
        from .models import ToBuy
        items = ToBuy.objects.all().order_by("-created_at")
        return Response([self._serialize(item) for item in items])

    def post(self, request):
        from .models import ToBuy
        data = request.data
        if not data.get("item_name"):
            logger.warning("ToBuyView.post: rejected — item_name is required")
            return Response({"error": "item_name is required"}, status=400)
        item = ToBuy.objects.create(
            item_name=data["item_name"],
            quantity=data.get("quantity", 1),
            price=data.get("price") or None,
            BuyingDate=data.get("BuyingDate") or None,
            Priority=data.get("Priority", "medium"),
            status=data.get("status", "pending"),
            notes=data.get("notes", ""),
            item_url=data.get("item_url", ""),
        )
        logger.info(f"ToBuyView.post: created item id={item.id} item_name={item.item_name} price={item.price}")
        return Response(self._serialize(item), status=201)

    def put(self, request):
        from .models import ToBuy
        data = request.data
        item_id = data.get("id")
        if not item_id:
            logger.warning("ToBuyView.put: rejected — ID is required for update")
            return Response({"error": "ID is required for update"}, status=400)
        try:
            item = ToBuy.objects.get(id=item_id)
        except ToBuy.DoesNotExist:
            logger.warning(f"ToBuyView.put: item not found id={item_id}")
            return Response({"error": "Item not found"}, status=404)
        item.item_name = data.get("item_name", item.item_name)
        item.quantity  = data.get("quantity",  item.quantity)
        item.price     = data.get("price",     item.price)
        item.BuyingDate= data.get("BuyingDate",item.BuyingDate) or None
        item.Priority  = data.get("Priority",  item.Priority)
        item.status    = data.get("status",    item.status)
        item.notes     = data.get("notes",     item.notes)
        item.item_url  = data.get("item_url",  item.item_url)
        item.save()
        print("Updated To-Buy item:", item.id, item.item_name, "Status:", item.status)
        logger.info(f"ToBuyView.put: updated item id={item.id} item_name={item.item_name} status={item.status} price={item.price}")
        if item.status == "purchased":
            print("Expected to create expenditure for purchased item.")
            expenditure = Expenditure.objects.create(
                amount=item.price or 0,
                category="to-buy",
                description=item.item_name,
                date=timezone.localdate(),
                notes=f"Auto-generated from To-Buy list item ID {item.id}"
            )
            logger.info(
                f"ToBuyView.put: auto-created Expenditure id={expenditure.id} amount={expenditure.amount} "
                f"for purchased ToBuy item id={item.id}"
            )
            all_base_income = Income.objects.aggregate(t=Sum("base_amount"))["t"] or 0
            all_expense     = Expenditure.objects.aggregate(t=Sum("amount"))["t"] or 0
            net_savings     = all_base_income - all_expense
            logger.info(
                f"ToBuyView.put: savings recalc after purchase all_base_income={all_base_income} "
                f"all_expense={all_expense} -> net_savings={net_savings}"
            )
        return Response(self._serialize(item))

    def delete(self, request):
        from .models import ToBuy
        item_id = request.query_params.get("id")
        if not item_id:
            logger.warning("ToBuyView.delete: rejected — ID is required")
            return Response({"error": "ID is required"}, status=400)
        try:
            ToBuy.objects.get(id=item_id).delete()
            logger.info(f"ToBuyView.delete: deleted item id={item_id}")
            return Response({"deleted": True})
        except ToBuy.DoesNotExist:
            logger.warning(f"ToBuyView.delete: item not found id={item_id}")
            return Response({"error": "Item not found"}, status=404)


class CanAffordView(APIView):
    def get(self, request):
        from .models import ToBuy
        today   = timezone.localdate()
        item_id = request.query_params.get("id")
        year    = int(request.query_params.get("year",  today.year))
        month   = int(request.query_params.get("month", today.month))

        if not item_id:
            logger.warning("CanAffordView.get: rejected — id is required")
            return Response({"error": "id is required"}, status=400)
        try:
            item = ToBuy.objects.get(id=item_id)
        except ToBuy.DoesNotExist:
            logger.warning(f"CanAffordView.get: item not found id={item_id}")
            return Response({"error": "Item not found"}, status=404)

        income      = Income.objects.aggregate(t=Sum("base_amount"))["t"] or 0
        expenditure = Expenditure.objects.aggregate(t=Sum("amount"))["t"] or 0
        money_left  = income - expenditure
        can_buy     = money_left >= (item.price or 0)
        logger.info(
            f"CanAffordView.get: item_id={item_id} item_price={item.price} total_income={income} "
            f"total_expenditure={expenditure} -> money_left={money_left} can_buy={can_buy}"
        )

        return Response({
            "can_buy":    can_buy,
            "money_left": float(money_left),
            "item_price": float(item.price) if item.price else None,
            "month":      month,
            "year":       year,
        })
