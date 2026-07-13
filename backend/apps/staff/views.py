from rest_framework import viewsets, status, serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.conf import settings as djconf
from django.db.models import Sum, Q
from decimal import Decimal
from datetime import datetime, timedelta, time
import datetime as dt
import calendar
import logging
from apps.notifications.utils import send_staff_notification

from .models import StaffMember, StaffShift, StaffAttendance, StaffPayment
from .serializers import (
    StaffSerializer, AttendanceSerializer, PaymentSerializer, StaffShiftSerializer
)

logger = logging.getLogger(__name__)


# ─── Salary → Finance helper ─────────────────────────────────────────────────

def _record_expense(staff, amount, month, paid_date):
    from apps.finances.models import Expenditure
    month_name = calendar.month_name[month.month]
    logger.info(
        f"_record_expense: staff={staff.id} ({staff.name}) amount={amount} "
        f"salary_month={month_name} {month.year} paid_date={paid_date} "
        f"-> finance will attribute this expense to paid_date's month/day"
    )

    # Recalculate att_pct just for the label
    days, counts = _build_staff_calendar(staff, month.year, month.month)
    working_days = counts["working_days"]
    days_present = (
        counts.get("present", 0) + counts.get("late", 0)
        + counts.get("overtime", 0) + counts.get("late_overtime", 0)
        + counts.get("half", 0) * 0.5
    )
    att_pct = round(days_present / working_days * 100, 1) if working_days > 0 else 0
    logger.info(
        f"_record_expense: staff={staff.id} salary_month={month_name} {month.year} "
        f"working_days={working_days} days_present={days_present} att_pct={att_pct}%"
    )

    exp = Expenditure.objects.create(
        category="salary",
        description=f"Salary — {staff.name} ({month_name} {month.year}) [{att_pct}% attendance]",
        amount=amount,
        date=paid_date,  # date = actual payment date so Finance reflects the month salary was credited
        vendor=staff.name,
        notes=(
            f"Role: {staff.role} | Shift: {staff.shift} | Month: {month_name} {month.year} "
            f"| Base: ₹{staff.salary} | Attendance: {att_pct}% | Payable: ₹{amount}"
        ),
    )
    logger.info(
        f"_record_expense: created Expenditure id={exp.id} staff={staff.id} amount={amount} "
        f"date={paid_date} (finance month={paid_date.month}/{paid_date.year})"
    )


def _delete_expense(staff, month):
    from apps.finances.models import Expenditure
    month_name = calendar.month_name[month.month]
    # Match by notes (correct month label) OR by date in that month (catches legacy records)
    deleted_count, _ = Expenditure.objects.filter(
        category="salary",
        vendor=staff.name,
        description__icontains=f"Salary — {staff.name} ({month_name} {month.year})",
    ).delete()
    logger.info(
        f"_delete_expense: staff={staff.id} ({staff.name}) salary_month={month_name} {month.year} "
        f"deleted_count={deleted_count}"
    )


# ─── Auto-absent helpers ─────────────────────────────────────────────────────

def _auto_mark_absent_staff():
    """
    For every active staff member, check today.
    If no attendance record exists AND yesterday was a working day per their
    shift template, AND the shift start+1hr has passed → mark auto_absent.
    Called lazily on list/calendar fetches.
    """
    today = timezone.localdate()
    now_time  = timezone.localtime(timezone.now()).time()   # IST local time

    for staff in StaffMember.objects.filter(status="active"):
        # Skip if record already exists
        if StaffAttendance.objects.filter(staff=staff, date=today).exists():
            continue

        shift = staff.get_shift_template()
        if shift:
            if not shift.is_working_day(today):
                continue
            # Only mark after shift_end + 1 hour today
            cutoff = (datetime.combine(dt.date.today(), shift.start_time) + timedelta(hours=1)).time()
            if now_time < cutoff:
                continue
        
        _, created = StaffAttendance.objects.get_or_create(
            staff=staff, date=today,
            defaults={"status": "auto_absent", "notes": "Auto-marked absent"},
        )
        if created:
            logger.info(
                f"_auto_mark_absent_staff: staff={staff.id} ({staff.name}) auto-marked absent "
                f"for date={today} (shift={shift.name if shift else 'none'})"
            )
            send_staff_notification(staff,"staff_absent")


def _auto_mark_absent_members():
    """
    For every active/expired member, mark absent for every past day (up to
    yesterday) that has no attendance record. Gym is open all 7 days.
    Only runs once per day effectively because get_or_create is idempotent.
    """
    from apps.members.models import Member, MemberAttendance
    yesterday = timezone.localdate() - timedelta(days=1)
    members   = list(Member.objects.filter(status__in=["active", "expired"]))
    logger.info(f"_auto_mark_absent_members: backfilling up to date={yesterday} for {len(members)} member(s)")
    for member in members:
        # Backfill from join_date up to yesterday for any missing day
        start = max(member.join_date, yesterday)   # only do yesterday for perf
        for delta in range((yesterday - start).days + 1):
            day = start + timedelta(days=delta)
            MemberAttendance.objects.get_or_create(
                member=member, date=day,
                defaults={"check_in": None, "check_out": None},
            )


# ─── Calendar builder ────────────────────────────────────────────────────────

def _build_staff_calendar(staff, year, month_num):
    """
    Returns a list of day dicts for the given month for one staff member.
    Each day: { date, weekday, is_working_day, status, check_in, check_out,
                worked_minutes, late_minutes, overtime_minutes, shift_start, shift_end }
    Plus summary counts.
    """
    shift       = staff.get_shift_template()
    _, num_days = calendar.monthrange(year, month_num)
    records     = {
        a.date: a
        for a in StaffAttendance.objects.filter(
            staff=staff, date__year=year, date__month=month_num
        )
    }

    days = []
    counts = {"present": 0, "absent": 0, "late": 0, "overtime": 0,
              "late_overtime": 0, "half": 0, "leave": 0, "auto_absent": 0,
              "working_days": 0,
              "total_worked_minutes": 0, "total_late_minutes": 0, "total_ot_minutes": 0}

    shift_day_mins = shift.shift_duration_minutes() if shift else 0

    for day_num in range(1, num_days + 1):
        d          = dt.date(year, month_num, day_num)
        is_future  = d > timezone.localdate()
        is_working = shift.is_working_day(d) if shift else True
        rec        = records.get(d)

        if is_working and not is_future:
            counts["working_days"] += 1

        wm = rec.worked_minutes   if rec else 0
        lm = rec.late_minutes     if rec else 0
        om = rec.overtime_minutes if rec else 0

        counts["total_worked_minutes"] += wm
        counts["total_late_minutes"]   += lm
        counts["total_ot_minutes"]     += om

        day_data = {
            "date":             str(d),
            "day_num":          day_num,
            "weekday":          d.strftime("%a"),
            "is_working_day":   is_working,
            "is_future":        is_future,
            "status":           rec.status    if rec else (None if is_future else "absent"),
            "check_in":         str(rec.check_in)  if rec and rec.check_in  else None,
            "check_out":        str(rec.check_out) if rec and rec.check_out else None,
            "worked_minutes":   wm,
            "late_minutes":     lm,
            "overtime_minutes": om,
            "shift_start":      str(shift.start_time) if shift else None,
            "shift_end":        str(shift.end_time)   if shift else None,
            "shift_duration":   shift_day_mins,
            "attendance_id":    rec.id if rec else None,
        }
        days.append(day_data)

        if not is_future and rec:
            st = rec.status
            if st in counts:
                counts[st] += 1

    # Total scheduled hours for the month = working_days × shift_duration
    counts["total_scheduled_minutes"] = counts["working_days"] * shift_day_mins

    logger.info(
        f"_build_staff_calendar: staff={staff.id} ({staff.name}) year={year} month={month_num} "
        f"shift={shift.name if shift else 'none'} working_days={counts['working_days']} "
        f"present={counts.get('present',0)} absent={counts.get('absent',0)} "
        f"late={counts.get('late',0)} overtime={counts.get('overtime',0)} "
        f"half={counts.get('half',0)} leave={counts.get('leave',0)} "
        f"auto_absent={counts.get('auto_absent',0)} "
        f"total_worked_minutes={counts['total_worked_minutes']} "
        f"total_scheduled_minutes={counts['total_scheduled_minutes']}"
    )

    return days, counts


def _build_member_calendar(member, year, month_num):
    """
    Returns calendar days for a member. All 7 days are working days (gym open daily).
    Status: present / absent only.
    """
    from apps.members.models import MemberAttendance

    _, num_days = calendar.monthrange(year, month_num)
    records = {
        a.date: a
        for a in MemberAttendance.objects.filter(
            member=member, date__year=year, date__month=month_num
        )
    }

    days   = []
    counts = {"present": 0, "absent": 0}

    for day_num in range(1, num_days + 1):
        d         = dt.date(year, month_num, day_num)
        is_future = d > timezone.localdate()
        rec       = records.get(d)

        status = None
        if not is_future:
            status = "present" if (rec and rec.check_in) else "absent"
            counts[status] += 1

        # Compute working minutes from check_in / check_out for display
        worked_minutes = 0
        if rec and rec.check_in and rec.check_out:
            from datetime import datetime as _dt
            base = d
            ci   = _dt.combine(base, rec.check_in)
            co   = _dt.combine(base, rec.check_out)
            if co < ci:
                from datetime import timedelta as _td
                co += _td(days=1)
            worked_minutes = max(0, int((co - ci).total_seconds() / 60))

        days.append({
            "date":           str(d),
            "day_num":        day_num,
            "weekday":        d.strftime("%a"),
            "is_future":      is_future,
            "status":         status,
            "check_in":       str(rec.check_in)  if rec and rec.check_in  else None,
            "check_out":      str(rec.check_out) if rec and rec.check_out else None,
            "worked_minutes": worked_minutes,
            "attendance_id":  rec.id if rec else None,
        })

    logger.info(
        f"_build_member_calendar: member={member.id} ({member.name}) year={year} month={month_num} "
        f"present={counts.get('present',0)} absent={counts.get('absent',0)}"
    )
    return days, counts


# ─── ViewSets ────────────────────────────────────────────────────────────────

class StaffShiftViewSet(viewsets.ModelViewSet):
    """CRUD for shift templates."""
    queryset         = StaffShift.objects.prefetch_related("staff_members").all()
    serializer_class = StaffShiftSerializer

    def destroy(self, request, *args, **kwargs):
        shift = self.get_object()
        logger.info(f"StaffShiftViewSet.destroy: shift={shift.id} ({shift.name})")
        # Unlink staff before deleting
        unlinked = StaffMember.objects.filter(shift_template=shift).update(shift_template=None)
        shift.delete()
        logger.info(f"StaffShiftViewSet.destroy: shift={shift.id} deleted, unlinked {unlinked} staff member(s)")
        return Response({"detail": "Shift deleted."}, status=204)


class StaffViewSet(viewsets.ModelViewSet):
    queryset         = StaffMember.objects.select_related("shift_template").all()
    serializer_class = StaffSerializer
    search_fields    = ["name", "phone", "email"]
    filterset_fields = ["role", "shift", "status"]

    def perform_create(self, serializer):
        staff = serializer.save()
        logger.info(
            f"StaffViewSet.create: staff={staff.id} ({staff.name}) role={staff.role} "
            f"shift={staff.shift} salary={staff.salary} status={staff.status}"
        )

    def perform_update(self, serializer):
        staff = serializer.save()
        logger.info(
            f"StaffViewSet.update: staff={staff.id} ({staff.name}) role={staff.role} "
            f"shift={staff.shift} salary={staff.salary} status={staff.status}"
        )

    def perform_destroy(self, instance):
        logger.info(f"StaffViewSet.destroy: staff={instance.id} ({instance.name})")
        instance.delete()

    @action(detail=False, methods=["get"])
    def stats(self, request):
        return Response({
            "total":    StaffMember.objects.count(),
            "active":   StaffMember.objects.filter(status="active").count(),
            "on_leave": StaffMember.objects.filter(status="on_leave").count(),
        })

    @action(detail=False, methods=["post"], url_path="generate-payments")
    def generate_payments(self, request):
        year       = int(request.data.get("year",  timezone.localdate().year))
        month      = int(request.data.get("month", timezone.localdate().month))
        month_date = dt.date(year, month, 1)
        logger.info(f"StaffViewSet.generate_payments: year={year} month={month} -> month_date={month_date}")
        created    = 0
        for staff in StaffMember.objects.filter(status="active", salary__gt=0):
            _, made = StaffPayment.objects.get_or_create(
                staff=staff, month=month_date,
                defaults={"amount": staff.salary, "status": "pending"}
            )
            if made:
                created += 1
        logger.info(f"StaffViewSet.generate_payments: month={month_date} created={created} payment record(s)")
        return Response({"created": created, "month": str(month_date)})

    # ── Per-staff calendar ────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="calendar")
    def calendar_view(self, request, pk=None):
        """
        GET /staff/members/{id}/calendar/?year=2026&month=3
        Returns full month calendar for this staff member.
        """
        _auto_mark_absent_staff()
        staff     = self.get_object()
        today     = timezone.localdate()
        year      = int(request.query_params.get("year",  today.year))
        month_num = int(request.query_params.get("month", today.month))
        logger.info(f"StaffViewSet.calendar_view: staff={staff.id} ({staff.name}) year={year} month={month_num}")

        days, counts = _build_staff_calendar(staff, year, month_num)
        shift = staff.get_shift_template()

        return Response({
            "staff_id":    staff.id,
            "staff_name":  staff.name,
            "role":        staff.role,
            "year":        year,
            "month":       month_num,
            "month_name":  calendar.month_name[month_num],
            "shift": {
                "id":          shift.id          if shift else None,
                "name":        shift.name        if shift else None,
                "start_time":  str(shift.start_time) if shift else None,
                "end_time":    str(shift.end_time)   if shift else None,
                "working_days": shift.working_day_names if shift else [],
                "late_grace":  shift.late_grace_minutes if shift else 0,
            },
            "days":   days,
            "counts": counts,
        })

    # ── Admin: mark attendance for a specific day ─────────────────────────────

    @action(detail=True, methods=["post"], url_path="mark-day")
    def mark_day(self, request, pk=None):
        """
        POST /staff/members/{id}/mark-day/
        Body: { date, status, check_in (opt), check_out (opt), notes (opt) }
        Creates or updates the attendance record for that day.
        """
        staff  = self.get_object()
        date_s = request.data.get("date")
        if not date_s:
            logger.warning(f"StaffViewSet.mark_day: rejected — staff={staff.id} ({staff.name}) missing 'date'")
            return Response({"detail": "date is required."}, status=400)

        try:
            date = dt.date.fromisoformat(date_s)
        except ValueError:
            logger.warning(
                f"StaffViewSet.mark_day: rejected — staff={staff.id} ({staff.name}) invalid date={date_s!r}"
            )
            return Response({"detail": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        status_val = request.data.get("status", "present")
        notes      = request.data.get("notes", "")
        logger.info(
            f"StaffViewSet.mark_day: staff={staff.id} ({staff.name}) date={date} status={status_val} "
            f"check_in={request.data.get('check_in')} check_out={request.data.get('check_out')}"
        )

        def _parse_time(val):
            """'HH:MM' or 'HH:MM:SS' string -> datetime.time, or None."""
            if not val:
                return None
            if isinstance(val, time):
                return val
            try:
                parts = [int(x) for x in str(val).split(":")]
                return time(*parts[:3])
            except (ValueError, TypeError):
                return None

        check_in  = _parse_time(request.data.get("check_in"))
        check_out = _parse_time(request.data.get("check_out"))

        # Absent / leave / auto_absent records must not carry stale times
        if status_val in ("absent", "auto_absent", "leave"):
            check_in  = None
            check_out = None

        rec, was_created = StaffAttendance.objects.update_or_create(
            staff=staff, date=date,
            defaults={
                "status":    status_val,
                "check_in":  check_in,
                "check_out": check_out,
                "notes":     notes,
            },
        )
        logger.info(
            f"StaffViewSet.mark_day: staff={staff.id} date={date} {'created' if was_created else 'updated'} "
            f"attendance id={rec.id} -> worked_minutes={rec.worked_minutes} late_minutes={rec.late_minutes} "
            f"overtime_minutes={rec.overtime_minutes} status={rec.status}"
        )
        return Response(AttendanceSerializer(rec).data)
    

    
    @action(detail=False, methods=["get"], url_path="salary-summary")
    def salary_summary(self, request):
        # GET /staff/members/salary-summary/?year=2026&month=3
        # Returns one row per active staff with attendance + salary breakdown.
        _auto_mark_absent_staff()
        today     = timezone.localdate()
        year      = int(request.query_params.get("year",  today.year))
        month_num = int(request.query_params.get("month", today.month))
        logger.info(f"StaffViewSet.salary_summary: year={year} month={month_num}")

        results = []
        for staff in StaffMember.objects.filter(status="active").select_related("shift_template"):
            days, counts = _build_staff_calendar(staff, year, month_num)

            base_salary          = float(staff.salary)
            working_days         = counts["working_days"]
            total_worked_mins    = counts["total_worked_minutes"]
            total_scheduled_mins = counts["total_scheduled_minutes"]
            total_late_mins      = counts["total_late_minutes"]
            total_ot_mins        = counts["total_ot_minutes"]

            days_present = (counts.get("present", 0) + counts.get("late", 0) +
                            counts.get("overtime", 0) + counts.get("late_overtime", 0) +
                            counts.get("half", 0) * 0.5)
            att_pct        = round(days_present / working_days * 100, 1) if working_days > 0 else 0
            billable_mins  = max(0, total_worked_mins)
            hours_pct      = round(billable_mins / total_scheduled_mins * 100, 1) if total_scheduled_mins > 0 else att_pct
            salary_payable = round(base_salary * hours_pct / 100, 2)
            logger.info(
                f"StaffViewSet.salary_summary calc: staff={staff.id} ({staff.name}) year={year} month={month_num} "
                f"base_salary={base_salary} working_days={working_days} days_present={days_present} "
                f"att_pct={att_pct}% billable_mins={billable_mins} total_scheduled_mins={total_scheduled_mins} "
                f"hours_pct={hours_pct}% -> salary_payable={salary_payable}"
            )

            month_date = dt.date(year, month_num, 1)
            payment    = StaffPayment.objects.filter(staff=staff, month=month_date).first()

            shift = staff.get_shift_template()
            results.append({
                "staff_id":             staff.id,
                "staff_name":           staff.name,
                "staff_role":           staff.role,
                "shift_name":           shift.name if shift else None,
                "shift_start":          str(shift.start_time) if shift else None,
                "shift_end":            str(shift.end_time)   if shift else None,
                "shift_day_minutes":    shift.shift_duration_minutes() if shift else 0,
                "base_salary":          base_salary,
                "working_days":         working_days,
                "days_present":         days_present,
                "days_absent":          counts.get("absent", 0) + counts.get("auto_absent", 0),
                "days_late":            counts.get("late", 0) + counts.get("late_overtime", 0),
                "days_ot":              counts.get("overtime", 0) + counts.get("late_overtime", 0),
                "days_leave":           counts.get("leave", 0),
                "days_half":            counts.get("half", 0),
                "attendance_pct":       att_pct,
                "hours_pct":            hours_pct,
                "total_scheduled_mins": total_scheduled_mins,
                "total_worked_mins":    total_worked_mins,
                "total_late_mins":      total_late_mins,
                "total_ot_mins":        total_ot_mins,
                "billable_mins":        billable_mins,
                "salary_payable":       salary_payable,
                "payment_id":           payment.id     if payment else None,
                "payment_status":       payment.status if payment else "no_record",
                "payment_amount":       float(payment.amount) if payment else salary_payable,
                "paid_date":            str(payment.paid_date) if payment and payment.paid_date else None,
            })

        return Response({"year": year, "month": month_num,
                         "month_name": calendar.month_name[month_num],
                         "staff": results})



class AttendanceViewSet(viewsets.ModelViewSet):
    queryset         = StaffAttendance.objects.select_related("staff").all()
    serializer_class = AttendanceSerializer
    filterset_fields = {
        "staff":  ["exact"],
        "date":   ["exact", "year", "month"],
        "status": ["exact"],
    }
    ordering_fields  = ["date"]

    def perform_create(self, serializer):
        rec = serializer.save()
        logger.info(
            f"AttendanceViewSet.create: staff={rec.staff_id} date={rec.date} status={rec.status} "
            f"check_in={rec.check_in} check_out={rec.check_out}"
        )

    def perform_update(self, serializer):
        rec = serializer.save()
        logger.info(
            f"AttendanceViewSet.update: attendance id={rec.id} staff={rec.staff_id} date={rec.date} "
            f"status={rec.status} check_in={rec.check_in} check_out={rec.check_out} "
            f"worked_minutes={rec.worked_minutes} late_minutes={rec.late_minutes} "
            f"overtime_minutes={rec.overtime_minutes}"
        )

    def perform_destroy(self, instance):
        logger.info(
            f"AttendanceViewSet.destroy: attendance id={instance.id} staff={instance.staff_id} "
            f"date={instance.date} status={instance.status}"
        )
        instance.delete()

    def list(self, request, *args, **kwargs):
        try:
            _auto_mark_absent_staff()
        except Exception:
            logger.exception("AttendanceViewSet.list: _auto_mark_absent_staff() failed")
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def today(self, request):
        today = timezone.localdate()
        qs    = StaffAttendance.objects.filter(date=today).select_related("staff")
        logger.info(f"AttendanceViewSet.today: date={today} record_count={qs.count()}")
        return Response(AttendanceSerializer(qs, many=True).data)

    @action(detail=False, methods=["post"])
    def bulk_mark(self, request):
        records = request.data.get("records", [])
        logger.info(f"AttendanceViewSet.bulk_mark: received {len(records)} record(s)")
        created = 0

        def _t(val):
            if not val: return None
            if isinstance(val, time): return val
            try:
                parts = [int(x) for x in str(val).split(":")]
                return time(*parts[:3])
            except (ValueError, TypeError):
                return None

        for r in records:
            StaffAttendance.objects.update_or_create(
                staff_id=r["staff"],
                date=r.get("date", timezone.localdate()),
                defaults={
                    "status":    r.get("status", "present"),
                    "check_in":  _t(r.get("check_in")),
                    "check_out": _t(r.get("check_out")),
                },
            )
            created += 1
        logger.info(f"AttendanceViewSet.bulk_mark: marked={created} of {len(records)} record(s)")
        return Response({"marked": created})

    @action(detail=False, methods=["post"], url_path="auto-absent")
    def auto_absent(self, request):
        """Manually trigger auto-absent logic (also called lazily on calendar fetch)."""
        logger.info("AttendanceViewSet.auto_absent: manually triggered")
        _auto_mark_absent_staff()
        _auto_mark_absent_members()
        return Response({"detail": "Auto-absent applied."})


# ── Member calendar endpoint ──────────────────────────────────────────────────

class MemberCalendarView(APIView):
    """
    GET /members/{id}/calendar/?year=2026&month=3
    Lives here because it needs the member calendar builder.
    Wire into members/urls.py as needed.
    """
    def get(self, request, pk):
        from apps.members.models import Member
        _auto_mark_absent_members()
        try:
            member = Member.objects.get(pk=pk)
        except Member.DoesNotExist:
            logger.warning(f"MemberCalendarView.get: member id={pk} not found")
            return Response({"detail": "Not found."}, status=404)

        today     = timezone.localdate()
        year      = int(request.query_params.get("year",  today.year))
        month_num = int(request.query_params.get("month", today.month))
        logger.info(f"MemberCalendarView.get: member={member.id} ({member.name}) year={year} month={month_num}")

        days, counts = _build_member_calendar(member, year, month_num)
        return Response({
            "member_id":   member.id,
            "member_name": member.name,
            "year":        year,
            "month":       month_num,
            "month_name":  calendar.month_name[month_num],
            "days":        days,
            "counts":      counts,
        })


class PaymentViewSet(viewsets.ModelViewSet):
    queryset         = StaffPayment.objects.select_related("staff").all()
    serializer_class = PaymentSerializer
    filterset_fields = ["staff", "status", "month"]

    def perform_create(self, serializer):
        p = serializer.save()
        logger.info(
            f"PaymentViewSet.create: payment id={p.id} staff={p.staff_id} month={p.month} "
            f"amount={p.amount} status={p.status}"
        )

    def perform_update(self, serializer):
        p = serializer.save()
        logger.info(
            f"PaymentViewSet.update: payment id={p.id} staff={p.staff_id} month={p.month} "
            f"amount={p.amount} status={p.status} paid_date={p.paid_date}"
        )

    def perform_destroy(self, instance):
        logger.info(
            f"PaymentViewSet.destroy: payment id={instance.id} staff={instance.staff_id} "
            f"month={instance.month} amount={instance.amount} status={instance.status}"
        )
        instance.delete()

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        p = self.get_object()
        logger.info(
            f"PaymentViewSet.mark_paid: payment id={p.id} staff={p.staff_id} ({p.staff.name}) "
            f"salary_month={p.month} current_status={p.status} base_amount={p.amount}"
        )
        if p.status == "paid":
            logger.warning(f"PaymentViewSet.mark_paid: rejected — payment id={p.id} already paid")
            return Response({"detail": "Already paid."}, status=400)

        try:
            # ── Recalculate attendance-based salary ──────────────────────────────
            days, counts = _build_staff_calendar(p.staff, p.month.year, p.month.month)

            working_days = counts["working_days"]
            days_present = (
                counts.get("present", 0)
                + counts.get("late", 0)
                + counts.get("overtime", 0)
                + counts.get("late_overtime", 0)
                + counts.get("half", 0) * 0.5
            )
            att_pct              = round(days_present / working_days * 100, 1) if working_days > 0 else 0
            total_worked_mins    = counts["total_worked_minutes"]
            total_scheduled_mins = counts["total_scheduled_minutes"]
            total_late_mins      = counts["total_late_minutes"]
            billable_mins        = max(0, total_worked_mins)
            hours_pct            = round(billable_mins / total_scheduled_mins * 100, 1) if total_scheduled_mins > 0 else att_pct
            salary_payable       = round(float(p.staff.salary) * hours_pct / 100, 2)
            logger.info(
                f"PaymentViewSet.mark_paid calc: payment id={p.id} staff={p.staff_id} salary_month={p.month} "
                f"base_salary={p.staff.salary} working_days={working_days} days_present={days_present} "
                f"att_pct={att_pct}% billable_mins={billable_mins} total_scheduled_mins={total_scheduled_mins} "
                f"total_late_mins={total_late_mins} hours_pct={hours_pct}% -> salary_payable={salary_payable}"
            )

            # Stamp the attendance-based amount onto the payment record
            p.amount    = salary_payable
            p.status    = "paid"
            p.paid_date = timezone.localdate()
            p.save()
            logger.info(
                f"PaymentViewSet.mark_paid: payment id={p.id} staff={p.staff_id} salary_month={p.month} "
                f"paid_date={p.paid_date} amount={p.amount} -> finance will attribute this to "
                f"{p.paid_date.month}/{p.paid_date.year} (payment month is {p.month.month}/{p.month.year})"
            )
            # ────────────────────────────────────────────────────────────────────

            _record_expense(p.staff, p.amount, p.month, p.paid_date)
        except Exception:
            logger.exception(
                f"PaymentViewSet.mark_paid: failed for payment id={p.id} staff={p.staff_id} month={p.month}"
            )
            raise
        return Response(PaymentSerializer(p).data)

    @action(detail=True, methods=["post"])
    def mark_unpaid(self, request, pk=None):
        p = self.get_object()
        logger.info(
            f"PaymentViewSet.mark_unpaid: payment id={p.id} staff={p.staff_id} ({p.staff.name}) "
            f"salary_month={p.month} current_status={p.status} amount={p.amount} paid_date={p.paid_date}"
        )
        if p.status != "paid":
            logger.warning(f"PaymentViewSet.mark_unpaid: rejected — payment id={p.id} not marked as paid")
            return Response({"detail": "Not marked as paid."}, status=400)
        try:
            _delete_expense(p.staff, p.month)
            p.status    = "pending"
            p.paid_date = None
            p.amount    = p.staff.salary  # reset to base so salary_summary recalculates fresh
            p.save()
            logger.info(
                f"PaymentViewSet.mark_unpaid: payment id={p.id} staff={p.staff_id} salary_month={p.month} "
                f"reset amount to base_salary={p.amount}"
            )
        except Exception:
            logger.exception(
                f"PaymentViewSet.mark_unpaid: failed for payment id={p.id} staff={p.staff_id} month={p.month}"
            )
            raise
        return Response(PaymentSerializer(p).data)