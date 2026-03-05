from django.contrib import admin

from .models import fraud_analysis


@admin.register(fraud_analysis)
class FraudAnalysisAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"username",
		"invoice_number",
		"risk_score",
		"risk_label",
		"is_fraud",
		"model_version",
		"created_at",
	)
	search_fields = ("username", "invoice_number")
	list_filter = ("risk_label", "is_fraud", "model_version")
