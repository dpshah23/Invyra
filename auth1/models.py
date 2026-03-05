from django.db import models
import bcrypt
import hashlib

# Create your models here.


class UserCustom(models.Model):
    username=models.CharField(max_length=150, unique=True)
    email=models.EmailField(unique=True)    
    name=models.CharField(max_length=150)
    password=models.CharField(max_length=255)
    created_at=models.DateTimeField(auto_now_add=True)
    lst_login=models.DateTimeField(auto_now=True)
    company_name=models.CharField(max_length=255, blank=True, null=True)
    status=models.CharField(max_length=20, default='active')

    def generateusername(self,email):
       
        base_username = email.split('@')[0]
        unique_username = base_username
        counter = 1

        while UserCustom.objects.filter(username=unique_username).exists():
            unique_username = f"{base_username}{counter}"
            counter += 1

        return unique_username


    def hashpassword(self,password):
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed_password.decode('utf-8')
    
    def check_password(self, password):
    
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))