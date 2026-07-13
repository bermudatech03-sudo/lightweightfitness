import logging
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Equipment, MaintenanceLog
from .serializers import EquipmentSerializer, MaintenanceLogSerializer

logger = logging.getLogger(__name__)


def _record_equipment_expense(equipment, amount, description, date):
    """Auto-create Expenditure when equipment is purchased or maintained."""
    if amount and float(amount) > 0:
        from apps.finances.models import Expenditure
        try:
            Expenditure.objects.create(
                category="equipment",
                description=description,
                amount=amount,
                date=date or timezone.localdate(),
                vendor="",
                notes=f"Equipment: {equipment.name}",
            )
            logger.info(f"[Equipment] Expense recorded for {equipment.name}: {description} amount={amount}")
        except Exception:
            logger.exception(f"[Equipment] Failed to record expense for {equipment.name} amount={amount}")
            raise


class EquipmentViewSet(viewsets.ModelViewSet):
    queryset = Equipment.objects.all()
    serializer_class = EquipmentSerializer
    search_fields    = ["name","brand","category"]
    filterset_fields = ["category","condition","is_active"]

    def perform_create(self, serializer):
        eq = serializer.save()
        logger.info(f"[Equipment] Created: id={eq.id} name={eq.name} category={eq.category}")
        # If purchase price provided, record as equipment expense
        if eq.purchase_price:
            _record_equipment_expense(
                eq, eq.purchase_price,
                f"Equipment Purchase — {eq.name}",
                eq.purchase_date or timezone.localdate(),
            )

    def perform_update(self, serializer):
        eq = serializer.save()
        logger.info(f"[Equipment] Updated: id={eq.id} name={eq.name} condition={eq.condition}")

    def perform_destroy(self, instance):
        logger.info(f"[Equipment] Deleted: id={instance.id} name={instance.name}")
        instance.delete()

    @action(detail=False, methods=["get"])
    def due_maintenance(self, request):
        today = timezone.localdate()
        qs = Equipment.objects.filter(next_service__lte=today, is_active=True)
        logger.info(f"[Equipment] due_maintenance check as of {today}: {qs.count()} item(s) due")
        return Response(EquipmentSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        return Response({
            "total":           Equipment.objects.filter(is_active=True).count(),
            "out_of_service":  Equipment.objects.filter(condition="out_of_service").count(),
            "due_maintenance": Equipment.objects.filter(
                next_service__lte=timezone.localdate(), is_active=True).count(),
        })


class MaintenanceLogViewSet(viewsets.ModelViewSet):
    queryset = MaintenanceLog.objects.select_related("equipment").all()
    serializer_class = MaintenanceLogSerializer
    filterset_fields = ["equipment"]

    def perform_create(self, serializer):
        log = serializer.save()
        logger.info(f"[Maintenance] Log created: id={log.id} equipment={log.equipment.name} date={log.date} cost={log.cost}")
        # Update equipment service dates
        if log.next_due:
            log.equipment.last_service = log.date
            log.equipment.next_service = log.next_due
            log.equipment.save()
            logger.info(
                f"[Maintenance] Equipment {log.equipment.name} service dates updated: "
                f"last_service={log.date} next_service={log.next_due}"
            )
        # Auto-record maintenance cost as expense
        if log.cost and float(log.cost) > 0:
            _record_equipment_expense(
                log.equipment, log.cost,
                f"Equipment Maintenance — {log.equipment.name}",
                log.date,
            )

    def perform_destroy(self, instance):
        logger.info(f"[Maintenance] Log deleted: id={instance.id} equipment={instance.equipment.name}")
        instance.delete()