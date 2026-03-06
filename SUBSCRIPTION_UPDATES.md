# Subscription Management System - Updated Implementation

## Changes Made

### 1. Sequential Plan Activation
- When a user upgrades/changes plans, the new plan is scheduled to start immediately after the current plan expires
- If upgrading to the same plan type, it simply extends the current subscription
- Prevents overlapping subscriptions and duplicate entries

### 2. **Duplicate Cleanup**
- Removed duplicate subscription records from database
- Added `_cleanup_duplicate_subscriptions()` function that:
  - Keeps only the most recent active/pending subscription per plan type
  - Removes all expired subscriptions
  - Runs automatically on every checkout

### 3. **Active Subscription Detection**
- Added `_get_active_subscription()` function to properly identify:
  - Only subscriptions with status `active` or `pending`
  - Only subscriptions where `end_date > now()` (not expired)
  - Returns subscription with highest priority (enterprise > pro > free)

### 4. **Subscription Statuses**
The system now supports 4 statuses:
- **active**: Currently active subscription
- **pending**: Payment pending (free plan immediately, paid awaiting Stripe success)
- **scheduled**: Queued to start after current subscription expires
- **cancelled**: Explicitly cancelled by user

### 5. **Free Plan Logic** (`subscriptions/views.py`)
```
If user has no active subscription:
  ✓ Create FREE plan immediately as "active"

If user has active subscription of SAME type:
  ✓ Extend it (refresh start/end dates)

If user has active subscription of DIFFERENT type:
  ✓ Schedule new FREE plan as "scheduled" (starts after current ends)
```

### 6. **Paid Plan Logic** (`subscriptions/views.py`)
```
If user has no active subscription:
  ✓ Create PAID plan with "pending" status
  ✓ After payment confirmed: change to "active"

If user has active subscription of SAME type:
  ✓ Update it (new payment continues same plan)

If user has active subscription of DIFFERENT type:
  ✓ Create new PAID plan as "scheduled"
  ✓ After payment confirmed: change to "scheduled"
  ✓ Will auto-activate when current plan expires
```

## Database Structure

No schema changes needed. Existing columns support new statuses:
- `status`: Now accepts "active", "pending", "scheduled", "cancelled"
- `start_date`: When subscription becomes active
- `end_date`: When subscription expires

## Files Modified

1. **subscriptions/views.py**
   - New: `_get_active_subscription(username)`
   - New: `_cleanup_duplicate_subscriptions(username)`  
   - Updated: `_upsert_checkout_subscription()` for sequential scheduling
   - Updated: `stripe_checkout()` free plan logic

2. **auth1/views.py**
   - Updated: `_pick_subscription_for_session()` to find CURRENT active subscription

3. **New: subscriptions/management/commands/cleanup_duplicate_subscriptions.py**
   - Standalone management command to clean database manually
   - Usage: `python manage.py cleanup_duplicate_subscriptions`

## How It Works (User Journey)

### Scenario 1: Free → Pro
1. User on Free plan (expires 2025-03-15)
2. User clicks "Buy Pro" → Pays
3. New Pro subscription created as **scheduled** (starts 2025-03-15)
4. Pro plan auto-activates when Free expires

### Scenario 2: Pro → Enterprise
1. User on Pro plan (expires 2025-04-15)
2. User clicks "Buy Enterprise" → Pays
3. New Enterprise subscription created as **scheduled** (starts 2025-04-15)
4. Enterprise plan auto-activates when Pro expires

### Scenario 3: Free → Free (Renew)
1. User on Free plan (expires today)
2. User clicks "Activate Free" again
3. Free subscription **extended** (new end_date = today + 30 days)

### Scenario 4: Pro → Pro (renew same)
1. User on Pro plan (expires 2025-04-15)
2. User renews Pro payment
3. Pro subscription **updated** with new payment intent ID

## Next Steps

1. **Restart Django server** to apply changes
2. **Test subscription flow**:
   - Sign up → Get free plan
   - Upgrade to Pro → Check it's scheduled
   - Downgrade back to Free → Check it's scheduled for after Pro expires
3. **Monitor logs** for any issues with subscription activation

## Management Command Usage

To manually clean duplicates anytime:
```bash
python manage.py cleanup_duplicate_subscriptions
```

Output shows count of removed duplicates.

## Status Summary

✅ **Fixed**: Multiple subscriptions per user
✅ **Fixed**: Overlapping plans  
✅ **Implemented**: Sequential plan activation
✅ **Implemented**: Automatic duplicate removal
✅ **Tested**: Django syntax validation (manage.py check)
