from django.db import models

# Create your models here.


class fraud_analysis(models.Model):
	username = models.CharField(max_length=150, db_index=True)
	invoice_id = models.IntegerField(blank=True, null=True)
	invoice_number = models.CharField(max_length=100, db_index=True)
	vendor_name = models.CharField(max_length=255, blank=True, default="")

	risk_score = models.FloatField(default=0)
	risk_label = models.CharField(max_length=20, default="low")
	is_fraud = models.BooleanField(default=False)
	reason = models.TextField(blank=True, default="")

	model_version = models.CharField(max_length=50, default="demo-rule-v1")
	features = models.JSONField(default=dict, blank=True)
	payload = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"{self.invoice_number} ({self.risk_label} - {self.risk_score:.2f})"
