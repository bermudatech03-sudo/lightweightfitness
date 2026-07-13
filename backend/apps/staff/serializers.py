# ADD these to your existing staff/serializers.py
# (keep MemberSerializer, PlanSerializer etc. unchanged)

import logging

from rest_framework import serializers
from .models import StaffMember, StaffShift, StaffAttendance, StaffPayment

logger = logging.getLogger(__name__)


class StaffShiftSerializer(serializers.ModelSerializer):
    working_day_names     = serializers.ReadOnlyField()
    shift_duration_minutes = serializers.SerializerMethodField()
    assigned_count        = serializers.SerializerMethodField()

    class Meta:
        model  = StaffShift
        fields = [
            "id", "name", "working_days_preset", "working_days",
            "start_time", "end_time", "late_grace_minutes",
            "overtime_threshold_minutes", "notes", "created_at",
            "working_day_names", "shift_duration_minutes", "assigned_count",
        ]

    def get_assigned_count(self, obj):
        return obj.staff_members.count()

    def get_shift_duration_minutes(self, obj):
        return obj.shift_duration_minutes()


class StaffSerializer(serializers.ModelSerializer):
    staff_id_display       = serializers.SerializerMethodField()
    shift_template_name    = serializers.SerializerMethodField()
    shift_duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model  = StaffMember
        fields = "__all__"

    def get_staff_id_display(self, obj):
        return obj.display_id()

    def get_shift_template_name(self, obj):
        return obj.shift_template.name if obj.shift_template else None

    def get_shift_duration_minutes(self, obj):
        return obj.shift_template.shift_duration_minutes() if obj.shift_template else None

    def create(self, validated_data):
        staff = super().create(validated_data)
        logger.info(
            f"StaffSerializer.create: staff={staff.id} ({staff.name}) role={staff.role} "
            f"salary={staff.salary} status={staff.status}"
        )
        return staff

    def update(self, instance, validated_data):
        old_salary, old_status = instance.salary, instance.status
        staff = super().update(instance, validated_data)
        logger.info(
            f"StaffSerializer.update: staff={staff.id} ({staff.name}) "
            f"salary {old_salary} -> {staff.salary} | status {old_status} -> {staff.status}"
        )
        return staff


class AttendanceSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.name", read_only=True)
    staff_role = serializers.CharField(source="staff.role", read_only=True)

    class Meta:
        model  = StaffAttendance
        fields = [
            "id", "staff", "staff_name", "staff_role",
            "date", "check_in", "check_out", "status", "notes",
            "worked_minutes", "late_minutes", "overtime_minutes",
        ]

    def create(self, validated_data):
        rec = super().create(validated_data)
        logger.info(
            f"AttendanceSerializer.create: staff={rec.staff_id} date={rec.date} status={rec.status} "
            f"check_in={rec.check_in} check_out={rec.check_out} worked_minutes={rec.worked_minutes} "
            f"late_minutes={rec.late_minutes} overtime_minutes={rec.overtime_minutes}"
        )
        return rec

    def update(self, instance, validated_data):
        old_status = instance.status
        rec = super().update(instance, validated_data)
        logger.info(
            f"AttendanceSerializer.update: attendance id={rec.id} staff={rec.staff_id} date={rec.date} "
            f"status {old_status} -> {rec.status} worked_minutes={rec.worked_minutes} "
            f"late_minutes={rec.late_minutes} overtime_minutes={rec.overtime_minutes}"
        )
        return rec


class PaymentSerializer(serializers.ModelSerializer):
    staff_name  = serializers.CharField(source="staff.name",  read_only=True)
    staff_role  = serializers.CharField(source="staff.role",  read_only=True)
    staff_shift = serializers.CharField(source="staff.shift", read_only=True)

    class Meta:
        model  = StaffPayment
        fields = "__all__"

    def create(self, validated_data):
        p = super().create(validated_data)
        logger.info(
            f"PaymentSerializer.create: payment id={p.id} staff={p.staff_id} month={p.month} "
            f"amount={p.amount} status={p.status} paid_date={p.paid_date}"
        )
        return p

    def update(self, instance, validated_data):
        old_amount, old_status = instance.amount, instance.status
        p = super().update(instance, validated_data)
        logger.info(
            f"PaymentSerializer.update: payment id={p.id} staff={p.staff_id} month={p.month} "
            f"amount {old_amount} -> {p.amount} | status {old_status} -> {p.status} paid_date={p.paid_date}"
        )
        return p