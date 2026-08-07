
from rest_framework import serializers
from .models import Notification, PushSubscription

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PushSubscription
        fields = ["id", "user_agent", "is_active", "created_at", "last_used_at"]


'''
API call / any trigger
       ↓
  send_notification()        ← utils.py: builds message, normalises phone
       ↓
  Notification.objects.create(status="pending")
       ↓
  post_save signal fires     ← signals.py: calls send_whatsapp_message()
       ↓
  Meta Cloud API             ← whatsapp.py: POST to graph.facebook.com
       ↓
  queryset.update(status="sent" / "failed")   ← no signal loop

'''