from django.db import models
from django.utils import timezone


class user_subscriptions(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    subscription_type = models.CharField(max_length=50)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, default="pending")
    autopay = models.BooleanField(default=False)

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="inr")
    plan_limit = models.CharField(max_length=50, blank=True, default="")

    payment_method = models.CharField(max_length=50, default="pending")
    stripe_session_id = models.CharField(max_length=255, blank=True, default="")
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    stripe_customer_email = models.EmailField(blank=True, default="")

    class Meta:
        db_table = "user_subscription"

    def __str__(self):
        return f"{self.username} - {self.subscription_type} ({self.status})"