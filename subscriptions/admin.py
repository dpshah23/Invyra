from django.contrib import admin

from .models import user_subscriptions


@admin.register(user_subscriptions)
class UserSubscriptionAdmin(admin.ModelAdmin):
	list_display = (
		"username",
		"subscription_type",
		"status",
		"amount",
		"currency",
		"payment_method",
		"start_date",
		"end_date",
	)
	search_fields = ("username", "stripe_session_id", "stripe_payment_intent_id")
	list_filter = ("subscription_type", "status", "payment_method", "autopay")
