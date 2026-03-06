from django.db import models

# Create your models here.

class Contact(models.Model):
    username = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    phone = models.CharField(max_length=20)

    def __str__(self):
        return self.username
    
    