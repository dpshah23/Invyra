from django.db import models

# Create your models here.


class invoices(models.Model):
    username = models.CharField(max_length=150, db_index=True, blank=True, default="")
    guest_session_id = models.CharField(max_length=50, db_index=True, blank=True, default="")
    invoice_number = models.CharField(max_length=100)
    vendor_name = models.CharField(max_length=255, blank=True, default="")
    invoice_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="USD")
    bank_account = models.CharField(max_length=64, blank=True, default="")

    raw_text = models.TextField(blank=True, default="")
    extracted_json = models.JSONField(default=dict, blank=True)
    ocr_confidence = models.FloatField(default=0)

    risk_score = models.FloatField(blank=True, null=True)
    risk_label = models.CharField(max_length=20, default="unknown")
    fraud_reason = models.TextField(blank=True, default="")

    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Invoice {self.invoice_number} for {self.username} - {self.status}"
    
class invoice_items(models.Model):
    invoice_id = models.ForeignKey(invoices, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    
    def __str__(self):
        return f"{self.description} - {self.quantity} x {self.unit_price} = {self.total_price}"
    
    
class blockchain_records(models.Model):
    invoice_id= models.ForeignKey(invoices, on_delete=models.CASCADE, related_name='blockchain_records')
    transaction_hash = models.CharField(max_length=255, blank=True, default="")
    invoice_hash = models.CharField(max_length=255, blank=True, default="")
    network = models.CharField(max_length=50, default="ethereum")
    timestamp = models.DateTimeField(auto_now_add=True)
    block_number = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Blockchain Record for Invoice {self.invoice_id.invoice_number} - TxHash: {self.transaction_hash}"  
    
class Vendor(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    total_invoices = models.IntegerField(default=0)
    total_amount_processed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    average_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    last_invoice_date = models.DateField(blank=True, null=True)
    risk_score = models.FloatField(default=50.0) # Base risk for unknown/new
    is_trusted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('username', 'name')

    def __str__(self):
        return f"{self.name} ({self.username})"
