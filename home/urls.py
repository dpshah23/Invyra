from django.urls import path
from .views import home_view,about,contact 

urlpatterns = [
    path('',home_view,name="home"),
    path('about_us/',about,name="about_us"),
    path('contact_us/',contact,name="contact_us")
]
