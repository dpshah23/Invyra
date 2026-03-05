from django.urls import path
from .views import *

urlpatterns = [
	path('upload/', invoice_upload, name='invoice_upload'),
]
