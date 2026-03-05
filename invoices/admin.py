from django.contrib import admin

from .models import invoice_items, invoices


@admin.register(invoices)
class InvoicesAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"username",
		"invoice_number",
		"vendor_name",
		"amount",
		"currency",
		"risk_label",
		"status",
		"created_at",
	)
	search_fields = ("username", "invoice_number", "vendor_name")
	list_filter = ("risk_label", "status", "currency")


@admin.register(invoice_items)
class InvoiceItemsAdmin(admin.ModelAdmin):
	list_display = ("id", "invoice_id", "description", "quantity", "unit_price", "total_price")
