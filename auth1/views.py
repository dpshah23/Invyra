from django.shortcuts import render,redirect

from auth1.models import UserCustom as User
from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
from subscriptions.models import user_subscriptions

# Create your views here.

POST_LOGIN_FALLBACK = '/auth/dashboard/'
PLAN_PRIORITY = {'free': 1, 'pro': 2, 'enterprise': 3}


def _normalize_plan_name(value):
    return (value or 'free').strip().lower()


def _pick_subscription_for_session(username):
    active_subscriptions = list(
        user_subscriptions.objects.filter(username=username, status='active')
    )
    if active_subscriptions:
        return max(
            active_subscriptions,
            key=lambda sub: (
                PLAN_PRIORITY.get(_normalize_plan_name(sub.subscription_type), 0),
                sub.end_date,
                sub.start_date,
                sub.id,
            ),
        )

    return (
        user_subscriptions.objects.filter(username=username)
        .order_by('-start_date', '-id')
        .first()
    )


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
            session.cycle_key()
            session['username'] = user.username
            session['email'] = user.email
            session['name'] = user.name

            # Get the user's subscription
            try:
                subscription = _pick_subscription_for_session(user.username)
                
                if subscription:
                    # User has an existing subscription - use it
                    session['subscription_type'] = _normalize_plan_name(subscription.subscription_type)
                    session['plan_limit'] = subscription.plan_limit or 10
                else:
                    # No subscription exists - create a default free one once.
                    subscription = user_subscriptions.objects.create(
                        username=user.username,
                        subscription_type='free',
                        status='active',
                        end_date=timezone.now() + timedelta(days=30),
                        plan_limit=10,
                    )
                    session['subscription_type'] = 'free'
                    session['plan_limit'] = subscription.plan_limit or 10
                
                session['is_authenticated'] = True
                
            except Exception as e:
                # Fallback if subscription retrieval fails
                session['subscription_type'] = 'free'
                session['is_authenticated'] = True
                session['plan_limit'] = 10
            
            # Update last login time
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
