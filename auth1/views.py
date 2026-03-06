from django.shortcuts import render,redirect

from auth1.models import UserCustom as User
from invoices.models import invoices
from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
from subscriptions.models import user_subscriptions
from random import randint

# Create your views here.

POST_LOGIN_FALLBACK = '/auth/dashboard/'
PLAN_PRIORITY = {'free': 1, 'pro': 2, 'enterprise': 3}


def _normalize_plan_name(value):
    return (value or 'free').strip().lower()


def _pick_subscription_for_session(username):
    """
    Pick the best subscription for the user:
    1. Auto-activate any scheduled subscriptions that are ready
    2. Prioritize ACTIVE subscriptions that are still valid (end_date in future)
    3. Then by plan tier (enterprise > pro > free)
    4. Then by soonest expiration
    5. Then most recently created
    """
    from django.db.models import Q
    from django.utils import timezone
    
    # Auto-activate scheduled subscriptions that are ready
    ready_to_activate = user_subscriptions.objects.filter(
        username=username,
        status='scheduled',
        start_date__lte=timezone.now()
    )
    for sub in ready_to_activate:
        sub.status = 'active'
        sub.save()
    
    # First, try to get an active and valid subscription
    active_subscriptions = list(
        user_subscriptions.objects.filter(
            username=username, 
            status__in=['active', 'pending'],
            end_date__gt=timezone.now()
        )
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

    # Fallback to most recent subscription of any type
    return (
        user_subscriptions.objects.filter(username=username)
        .order_by('-start_date', '-id')
        .first()
    )


def get_dashboard_context(username):
    import json
    from django.db.models import Sum, Count
    from django.utils import timezone
    from datetime import timedelta
    from invoices.models import invoices
    
    user_invoices = invoices.objects.filter(username=username).order_by('-created_at')
    
    total_invoices = user_invoices.count()
    
    # Amount saved (sum of flagged/rejected invoices)
    fraudulent_invoices = user_invoices.filter(status__in=['flagged', 'rejected'])
    amount_saved = fraudulent_invoices.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Fraud detection rate
    fraud_count = fraudulent_invoices.count()
    fraud_rate = (fraud_count / total_invoices * 100) if total_invoices > 0 else 0
    
    # Average risk score
    # Filter out invoices without a score
    scored_invoices = user_invoices.exclude(risk_score__isnull=True)
    scored_count = scored_invoices.count()
    avg_risk_score = (scored_invoices.aggregate(Sum('risk_score'))['risk_score__sum'] or 0) / scored_count if scored_count > 0 else 0
    
    recent_invoices = user_invoices[:5]
    all_invoices = user_invoices

    # Chart 1: Risk Distribution
    risk_distribution = {
        'Low Risk': user_invoices.filter(risk_label='low').count() or 0,
        'Medium Risk': user_invoices.filter(risk_label='medium').count() or 0,
        'High Risk': user_invoices.filter(risk_label='high').count() or 0,
        'Critical Risk': user_invoices.filter(risk_label='critical').count() or 0,
    }

    # Chart 2: Fraud Types Detected
    fraud_types_qs = fraudulent_invoices.exclude(fraud_reason='').values('fraud_reason').annotate(count=Count('id')).order_by('-count')[:5]
    fraud_types = {item['fraud_reason']: item['count'] for item in fraud_types_qs}
    if not fraud_types:
        fraud_types = {'None': 0}

    # Chart 3: Processing Trends (Last 4 Weeks)
    trends = {'labels': [], 'processed': [], 'flagged': [], 'rejected': []}
    today = timezone.now().date()
    # Go back 4 weeks
    for i in range(3, -1, -1):
        start_date = today - timedelta(days=today.weekday() + (i * 7))
        end_date = start_date + timedelta(days=6)
        trends['labels'].append(f"{start_date.strftime('%b %d')}")
        
        week_invoices = user_invoices.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        trends['processed'].append(week_invoices.filter(status__in=['processed', 'blockchain_recorded']).count())
        trends['flagged'].append(week_invoices.filter(status='flagged').count())
        trends['rejected'].append(week_invoices.filter(status='rejected').count())

    return {
        'total_invoices': total_invoices,
        'amount_saved': float(amount_saved),
        'fraud_rate': round(fraud_rate, 1),
        'fraud_count': fraud_count,
        'avg_risk_score': round(avg_risk_score, 1),
        'recent_invoices': recent_invoices,
        'all_invoices': all_invoices,
        # JSON dumps for charts
        'risk_labels': json.dumps(list(risk_distribution.keys())),
        'risk_data': json.dumps(list(risk_distribution.values())),
        'fraud_labels': json.dumps(list(fraud_types.keys())),
        'fraud_data': json.dumps(list(fraud_types.values())),
        'trend_labels': json.dumps(trends['labels']),
        'trend_processed': json.dumps(trends['processed']),
        'trend_flagged': json.dumps(trends['flagged']),
        'trend_rejected': json.dumps(trends['rejected']),
    }


def dashboard(request):
    username = request.session.get('username')
    if not username:
        return redirect('/auth/login/')
        
    context = get_dashboard_context(username)
    context['name'] = request.session.get('name', '')
    
    return render(request, 'dashboard.html', context)

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
        
        # Migrate guest invoices to newly registered user (if any)
        guest_session_id = request.session.get('guest_session_id')
        if guest_session_id:
            invoices.objects.filter(guest_session_id=guest_session_id).update(
                username=username,
                guest_session_id=""  # Clear guest session ID
            )
        
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
            
            # Migrate any guest invoices to this newly logged-in user
            old_guest_session_id = request.session.get('guest_session_id')
            if old_guest_session_id:
                invoices.objects.filter(guest_session_id=old_guest_session_id).update(
                    username=user.username,
                    guest_session_id=""  # Clear guest session ID
                )

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
            
            # Clear guest session ID after migration
            if 'guest_session_id' in session:
                del session['guest_session_id']
            if 'is_guest' in session:
                del session['is_guest']

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

def guest_session(request):
    """
    Redirect guest users to invoice upload page.
    GuestSessionMiddleware will auto-assign guest_session_id on the request.
    """
    return redirect('/invoices/upload/')
