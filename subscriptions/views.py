import json
from datetime import timedelta
from decimal import Decimal
import logging

import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import user_subscriptions

import time

logger = logging.getLogger(__name__)


def _safe_int_setting(name, default_value, min_value):
    try:
        value = int(getattr(settings, name, default_value))
    except (TypeError, ValueError):
        return default_value
    return max(min_value, value)


STRIPE_REQUEST_TIMEOUT_SECONDS = _safe_int_setting("STRIPE_REQUEST_TIMEOUT_SECONDS", 12, 3)
STRIPE_CHECKOUT_RETRY_COUNT = _safe_int_setting("STRIPE_CHECKOUT_RETRY_COUNT", 1, 1)

def _validate_stripe_config():
    """Validate Stripe API key is properly configured"""
    api_key = getattr(settings, "SK_KEY", "").strip()
    if not api_key:
        return False, "Stripe API key (SK_KEY) is not configured. Check your environment variables."
    if not api_key.startswith(("sk_live_", "sk_test_")):
        return False, "Invalid Stripe API key format. Should start with 'sk_live_' or 'sk_test_'."
    stripe.api_key = api_key
    return True, "Stripe configured successfully"


def _configure_stripe_http_client():
    # Keep checkout responsive even when Stripe network connectivity is poor.
    try:
        stripe.default_http_client = stripe.http_client.RequestsClient(
            timeout=STRIPE_REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        # If Stripe internals differ by version, continue with default client.
        pass

# Initial validation
_validate_stripe_config()
_configure_stripe_http_client()

PLAN_CATALOG = {
    "Free": {
        "amount": Decimal("0.00"),
        "currency": "usd",
        "limit": "10",
        "description": "10 invoice analyses/month with basic fraud detection",
        "duration_days": 30,
    },
    "Pro": {
        "amount": Decimal("9.99"),
        "currency": "usd",
        "limit": "1000",
        "description": "1000 invoice analyses/month with advanced fraud detection",
        "duration_days": 30,
    },
    "Enterprise": {
        "amount": Decimal("19.99"),
        "currency": "usd",
        "limit": "Unlimited",
        "description": "Unlimited invoice analyses with enterprise features",
        "duration_days": 30,
    },
}


def _normalize_plan_name(plan_name):
    return (plan_name or "").strip().lower()


def _get_active_subscription(username):
    """Get the currently active subscription, if any."""
    from django.db.models import Q
    return user_subscriptions.objects.filter(
        username=username,
        status__in=["active", "pending"],
        end_date__gt=timezone.now()
    ).order_by("-end_date", "-id").first()


def _cleanup_duplicate_subscriptions(username):
    """Remove duplicate/inactive subscriptions for a user, keeping only the most recent of each type."""
    from django.db.models import Max, F
    
    # Get the most recent active/pending subscription of each type
    kept_subscriptions = set()
    
    for sub_type in ["free", "pro", "enterprise"]:
        latest = user_subscriptions.objects.filter(
            username=username,
            subscription_type=sub_type,
            status__in=["active", "pending"]
        ).order_by("-start_date", "-id").first()
        
        if latest:
            kept_subscriptions.add(latest.id)
    
    # Delete all other subscriptions for this user (keep only one active per plan type)
    user_subscriptions.objects.filter(
        username=username,
        status__in=["active", "pending"]
    ).exclude(id__in=kept_subscriptions).delete()
    
    # Delete all expired subscriptions
    user_subscriptions.objects.filter(
        username=username,
        end_date__lte=timezone.now()
    ).delete()


def _get_checkout_payment_methods():
    configured = getattr(settings, "STRIPE_PAYMENT_METHOD_TYPES", ["card"])

    if isinstance(configured, str):
        methods = [item.strip() for item in configured.split(",") if item.strip()]
    elif isinstance(configured, (list, tuple, set)):
        methods = [str(item).strip() for item in configured if str(item).strip()]
    else:
        methods = ["card"]

    if "card" not in methods:
        methods.insert(0, "card")

    # Deduplicate while preserving order.
    unique_methods = []
    seen = set()
    for method in methods:
        if method not in seen:
            unique_methods.append(method)
            seen.add(method)

    return unique_methods or ["card"]


def _create_checkout_session(domain, plan, plan_name, email, username, payment_methods):
    # Retry only transient Stripe network failures.
    for attempt in range(STRIPE_CHECKOUT_RETRY_COUNT):
        try:
            return stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=payment_methods,
                line_items=[
                    {
                        "price_data": {
                            "currency": plan["currency"],
                            "product_data": {
                                "name": f"Invyra {plan_name} Plan",
                                "description": plan["description"],
                            },
                            "unit_amount": int(plan["amount"] * 100),
                        },
                        "quantity": 1,
                    }
                ],
                success_url=f"{domain}{reverse('stripe_success')}?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{domain}{reverse('stripe_cancel')}",
                customer_email=email or None,
                metadata={
                    "username": username,
                    "plan_name": plan_name,
                    "plan_limit": plan["limit"],
                },
            )
        except stripe.error.APIConnectionError as exc:
            logger.warning(
                "Stripe API connection error during checkout session creation (attempt %s/%s): %s",
                attempt + 1,
                STRIPE_CHECKOUT_RETRY_COUNT,
                str(exc),
            )
            if attempt == STRIPE_CHECKOUT_RETRY_COUNT - 1:
                raise
            time.sleep(0.4)


def _login_redirect(request):
    request.session["post_login_next"] = reverse("pricing")
    return redirect(f"{reverse('login')}?next={reverse('pricing')}")


def _get_domain(request):
    configured_domain = getattr(settings, "DOMAIN", "").strip().rstrip("/")
    if configured_domain:
        return configured_domain
    return request.build_absolute_uri("/").rstrip("/")


def _plan_end_date(plan_name):
    return timezone.now() + timedelta(days=PLAN_CATALOG[plan_name]["duration_days"])


def _upsert_checkout_subscription(checkout_session, status_override=None):
    metadata = checkout_session.get("metadata") or {}
    session_id = checkout_session.get("id", "")
    plan_name = metadata.get("plan_name", "")
    username = metadata.get("username", "")

    if not session_id or not username or plan_name not in PLAN_CATALOG:
        return None

    plan = PLAN_CATALOG[plan_name]
    normalized_plan = _normalize_plan_name(plan_name)
    payment_methods = checkout_session.get("payment_method_types") or []
    payment_method = payment_methods[0] if payment_methods else "card"
    payment_intent = checkout_session.get("payment_intent") or ""
    if isinstance(payment_intent, dict):
        payment_intent_id = payment_intent.get("id", "")
    else:
        payment_intent_id = payment_intent

    customer_email = checkout_session.get("customer_email") or ""
    if not customer_email:
        customer_details = checkout_session.get("customer_details") or {}
        customer_email = customer_details.get("email", "")

    checkout_status = "active" if checkout_session.get("payment_status") == "paid" else "pending"
    final_status = status_override or checkout_status

    # Clean up duplicates
    _cleanup_duplicate_subscriptions(username)
    
    # Check for active subscription
    active_sub = _get_active_subscription(username)
    
    # Determine when the new subscription should start
    if active_sub and active_sub.subscription_type != normalized_plan:
        # Different plan type - schedule to start after current subscription expires
        start_date = active_sub.end_date
        new_status = "scheduled" if final_status == "active" else "pending"
    else:
        # Same plan or no active subscription - start immediately
        start_date = timezone.now()
        new_status = final_status

    subscription, created = user_subscriptions.objects.get_or_create(
        stripe_session_id=session_id,
        defaults={
            "username": username,
            "subscription_type": normalized_plan,
            "start_date": start_date,
            "end_date": start_date + timedelta(days=plan["duration_days"]),
            "status": new_status,
            "autopay": False,
            "amount": plan["amount"],
            "currency": plan["currency"],
            "plan_limit": plan["limit"],
            "payment_method": payment_method,
            "stripe_payment_intent_id": payment_intent_id or "",
            "stripe_customer_email": customer_email,
        },
    )

    if not created:
        subscription.username = username
        subscription.subscription_type = normalized_plan
        subscription.start_date = start_date
        subscription.end_date = start_date + timedelta(days=plan["duration_days"])
        subscription.status = new_status
        subscription.autopay = False
        subscription.amount = plan["amount"]
        subscription.currency = plan["currency"]
        subscription.plan_limit = plan["limit"]
        subscription.payment_method = payment_method
        subscription.stripe_payment_intent_id = payment_intent_id or ""
        subscription.stripe_customer_email = customer_email
        subscription.save()

    return subscription


def pricing(request):
    return render(
        request,
        "pricing.html",
        {
            "stripe_pk_key": getattr(settings, "PK_KEY", ""),
            "session_username": request.session.get("username", ""),
        },
    )


@require_POST
def stripe_checkout(request):
    username = request.session.get("username")
    if not username:
        request.session["pending_plan"] = (request.POST.get("plan_name") or "").strip()
        return _login_redirect(request)

    requested_plan = (request.POST.get("plan_name") or "").strip()
    plan_name = next(
        (name for name in PLAN_CATALOG if name.lower() == requested_plan.lower()),
        "",
    )
    if not plan_name:
        return HttpResponseBadRequest("Invalid plan selected.")

    plan = PLAN_CATALOG[plan_name]
    normalized_plan = _normalize_plan_name(plan_name)
    email = request.session.get("email", "")

    # Clean up duplicates first
    _cleanup_duplicate_subscriptions(username)
    
    if plan["amount"] == Decimal("0.00"):
        # Free plan: check for active subscription
        active_sub = _get_active_subscription(username)
        
        if active_sub:
            # If user has active subscription, schedule free plan to start after current expires
            if active_sub.subscription_type == normalized_plan:
                # Same plan type - just refresh it
                active_sub.start_date = timezone.now()
                active_sub.end_date = _plan_end_date(plan_name)
                active_sub.status = "active"
                active_sub.save()
            else:
                # Different plan - schedule new free plan to start after current ends
                user_subscriptions.objects.create(
                    username=username,
                    subscription_type=normalized_plan,
                    start_date=active_sub.end_date,
                    end_date=active_sub.end_date + timedelta(days=PLAN_CATALOG[plan_name]["duration_days"]),
                    status="scheduled",
                    autopay=False,
                    amount=plan["amount"],
                    currency=plan["currency"],
                    plan_limit=plan["limit"],
                    payment_method="free",
                    stripe_customer_email=email,
                )
        else:
            # No active subscription - create immediately
            user_subscriptions.objects.create(
                username=username,
                subscription_type=normalized_plan,
                start_date=timezone.now(),
                end_date=_plan_end_date(plan_name),
                status="active",
                autopay=False,
                amount=plan["amount"],
                currency=plan["currency"],
                plan_limit=plan["limit"],
                payment_method="free",
                stripe_customer_email=email,
            )

        return HttpResponse(
            "Free subscription activated successfully. <a href='/subscriptions/pricing/'>Back to pricing</a>"
        )

    if not stripe.api_key:
        return HttpResponseBadRequest("Stripe is not configured. Set SK_KEY in settings or environment.")

    domain = _get_domain(request)
    payment_methods = _get_checkout_payment_methods()

    try:
        checkout_session = _create_checkout_session(
            domain=domain,
            plan=plan,
            plan_name=plan_name,
            email=email,
            username=username,
            payment_methods=payment_methods,
        )
    except stripe.error.APIConnectionError:
        return HttpResponseBadRequest(
            "Stripe network error while creating checkout session. "
            "Please retry in a few seconds."
        )
    except stripe.error.InvalidRequestError as exc:
        if "Invalid payment_method_types" not in str(exc):
            return HttpResponseBadRequest(
                f"Stripe error ({plan['currency']} {plan['amount']}): {str(exc)}"
            )

        try:
            checkout_session = _create_checkout_session(
                domain=domain,
                plan=plan,
                plan_name=plan_name,
                email=email,
                username=username,
                payment_methods=["card"],
            )
        except stripe.error.APIConnectionError:
            return HttpResponseBadRequest(
                "Stripe network error while creating checkout session. "
                "Please retry in a few seconds."
            )
        except stripe.error.StripeError as nested_exc:
            return HttpResponseBadRequest(
                f"Stripe error ({plan['currency']} {plan['amount']}): {str(nested_exc)}"
            )
    except stripe.error.StripeError as exc:
        return HttpResponseBadRequest(
            f"Stripe error ({plan['currency']} {plan['amount']}): {str(exc)}"
        )

    user_subscriptions.objects.get_or_create(
        stripe_session_id=checkout_session.id,
        defaults={
            "username": username,
            "subscription_type": normalized_plan,
            "start_date": timezone.now(),
            "end_date": _plan_end_date(plan_name),
            "status": "pending",
            "autopay": False,
            "amount": plan["amount"],
            "currency": plan["currency"],
            "plan_limit": plan["limit"],
            "payment_method": "pending",
            "stripe_customer_email": email,
        },
    )

    return redirect(checkout_session.url, code=303)


def stripe_success(request):
    username = request.session.get("username")
    if not username:
        return _login_redirect(request)

    session_id = (request.GET.get("session_id") or "").strip()
    if not session_id:
        return redirect("pricing")

    if not stripe.api_key:
        return HttpResponseBadRequest("Stripe is not configured. Set SK_KEY in settings or environment.")

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.APIConnectionError:
        return HttpResponseBadRequest(
            "Stripe network error while verifying payment. Please retry in a few seconds."
        )
    except stripe.error.StripeError as exc:
        return HttpResponseBadRequest(f"Unable to verify Stripe session: {str(exc)}")

    metadata = checkout_session.get("metadata") or {}
    if metadata.get("username") and metadata.get("username") != username:
        return HttpResponseBadRequest("Session user mismatch.")

    if checkout_session.get("payment_status") != "paid":
        return HttpResponse(
            "Payment is not completed yet. <a href='/subscriptions/pricing/'>Return to pricing</a>"
        )

    _upsert_checkout_subscription(checkout_session, status_override="active")
    return HttpResponse(
        "Payment successful and subscription activated. <a href='/subscriptions/pricing/'>Back to pricing</a>"
    )


def stripe_cancel(request):
    username = request.session.get("username")
    if not username:
        return _login_redirect(request)

    session_id = (request.GET.get("session_id") or "").strip()
    if session_id:
        user_subscriptions.objects.filter(
            username=username,
            stripe_session_id=session_id,
            status="pending",
        ).update(status="cancelled")

    return HttpResponse("Payment cancelled. <a href='/subscriptions/pricing/'>Back to pricing</a>")


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = json.loads(payload.decode("utf-8"))
    except ValueError:
        return HttpResponseBadRequest("Invalid payload")
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest("Invalid signature")

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        _upsert_checkout_subscription(event_data, status_override="active")
    elif event_type == "checkout.session.expired":
        session_id = event_data.get("id", "")
        if session_id:
            user_subscriptions.objects.filter(stripe_session_id=session_id).update(status="cancelled")

    return JsonResponse({"status": "ok"})