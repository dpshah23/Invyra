from django.shortcuts import render,redirect

from auth1.models import UserCustom as User
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

# Create your views here.

POST_LOGIN_FALLBACK = '/auth/dashboard/'


def dashboard(request):
    if not request.session.get('username'):
        return redirect('/auth/login/')
    return render(request, 'dashboard.html', {'name': request.session.get('name', '')})

@ratelimit(key='ip', rate='5/m', block=True)
def signup(request):
    
    if request.session.get('username'):
        return redirect(POST_LOGIN_FALLBACK)

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        name = (request.POST.get('name') or '').strip()
        password = request.POST.get('password') or ''
        compname = (request.POST.get('compname') or '').strip()

        if not email or not name or not password:
            return render(request, 'login.html', {'error': 'Name, email and password are required'})

        if User.objects.filter(email__iexact=email).exists():
            return render(request, 'login.html', {'error': 'Email already exists'})

        username = User().generateusername(email)
        user = User(username=username, email=email, name=name, lst_login=None, company_name=compname)
        user.set_password(password)
        user.save()
        return render(request, 'login.html', {'success': 'Account created. Please sign in.'})

    return render(request,'login.html')

@ratelimit(key='ip', rate='5/m', block=True)
def login(request):

    next_path = (request.GET.get('next') or '').strip()
    if next_path.startswith('/'):
        request.session['post_login_next'] = next_path

    if request.session.get('username'):
        return redirect(POST_LOGIN_FALLBACK)

    if request.method == 'POST':
        email = (request.POST.get('email') or request.POST.get('username') or '').strip().lower()
        password = request.POST.get('password') or ''

        if not email or not password:
            return render(request, 'login.html', {'error': 'Email and password are required'})

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return render(request, 'login.html', {'error': 'Invalid email or password'})

        if user.check_password(password):
            session = request.session
            # session['user_id'] = user.id
            session.cycle_key()
            session['username'] = user.username
            session['email'] = user.email
            session['name'] = user.name

            # update last login time to now
            user.lst_login = timezone.now()
            user.save()

            redirect_path = request.session.pop('post_login_next', '')
            if redirect_path.startswith('/'):
                return redirect(redirect_path)

            return redirect(POST_LOGIN_FALLBACK)

        return render(request, 'login.html', {'error': 'Invalid email or password'})

    return render(request,'login.html')

@ratelimit(key='ip', rate='5/m', block=True)
def logout(request):
    request.session.flush()
    return render(request,'login.html')


# def guest_session(request)
