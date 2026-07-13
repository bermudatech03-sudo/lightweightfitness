import logging
from rest_framework import serializers
from .models import Income, Expenditure

logger = logging.getLogger(__name__)

class IncomeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Income
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        logger.info(
            f"IncomeSerializer.validate: base_amount={attrs.get('base_amount')} gst_rate={attrs.get('gst_rate')} "
            f"gst_amount={attrs.get('gst_amount')} amount={attrs.get('amount')} category={attrs.get('category')} "
            f"date={attrs.get('date')} invoice_number={attrs.get('invoice_number')}"
        )
        return attrs

class ExpenditureSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Expenditure
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        logger.info(
            f"ExpenditureSerializer.validate: category={attrs.get('category')} amount={attrs.get('amount')} "
            f"date={attrs.get('date')} vendor={attrs.get('vendor')}"
        )
        return attrs