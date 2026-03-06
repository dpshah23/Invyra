from django.shortcuts import render,redirect

# Create your views here.
def home_view(request):
    return render(request,"home.html")

def about(request):
    return render(request,"about.html")

def contact(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        message = request.POST.get("message")
        phone = request.POST.get("phone")

        
        from .models import Contact
        contact = Contact(username=username, email=email, message=message, phone=phone)
        contact.save()

        return redirect("/")

    return render(request,"contact-us.html")