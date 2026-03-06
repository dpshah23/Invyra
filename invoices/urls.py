from django.urls import path
from . import views

urlpatterns = [
	path('upload/', views.invoice_upload, name='invoice_upload'),
    path('<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('save_blockchain_record/', views.save_blockchain_record, name='save_blockchain_record')
]
