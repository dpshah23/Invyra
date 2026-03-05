from django.db import models
import bcrypt
import hashlib

# Create your models here.


class UserCustom(models.Model):
    username=models.CharField(max_length=150, unique=True)
    email=models.EmailField(unique=True)    
    name=models.CharField(max_length=150)
    password=models.CharField(max_length=255)

    def hashpassword(self,password):
        # Hash the password using bcrypt
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed_password.decode('utf-8')
    
    def check_password(self, password):
        
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))