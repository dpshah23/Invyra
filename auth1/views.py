from urllib import request

from django.shortcuts import render

from auth1.models import UserCustom as User

# Create your views here.

def signup(request):

    if request.method == 'POST':
        print("Signup form submitted")
        
        email = request.POST.get('email')
        name = request.POST.get('name')
        password = request.POST.get('password')
        compname=request.POST.get('compname')

        username=User().generateusername(email)
        user = User(username=username,email=email,name=name,lstlogin=None,company_name=compname)
        user.password = user.hashpassword(password)  
        user.save() 
    return render(request,'login.html')

def login(request):

    if request.method == 'POST':
            username = request.POST.get('username')
            password = request.POST.get('password')

            try:
                user = User.objects.get(username=username)
                if user.check_password(password):
                    print("Login successful")
                    session = request.session
                    # session['user_id'] = user.id
                    session['username'] = user.username
                    session['name'] = user.name

                    # update last login time to now
                    
                    return render(request,'welcome.html',{'name':user.name})
                else:
                    print("Unexpected error occured")
                    return render(request,'login.html',{'error':'Invalid password'})
            except User.DoesNotExist:
                return render(request,'login.html',{'error':'User does not exist'})
    return render(request,'login.html')

def logout(request):
    request.session.flush()
    return render(request,'login.html')

