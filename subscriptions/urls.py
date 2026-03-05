from django.urls import path
from .views import *

urlpatterns = [
    path('pricing/', pricing, name='pricing'),
    path('checkout/', stripe_checkout, name='stripe_checkout'),
    path('success/', stripe_success, name='stripe_success'),
    path('cancel/', stripe_cancel, name='stripe_cancel'),
    path('webhook/', stripe_webhook, name='stripe_webhook'),
]
