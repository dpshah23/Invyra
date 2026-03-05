from django.urls import path
from .views import *

urlpatterns = [
	path('detect-risk/', detect_risk, name='detect_risk'),
]


