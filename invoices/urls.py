from django.urls import path
from . import views

urlpatterns = [
	path('upload/', views.invoice_upload, name='invoice_upload'),
]
