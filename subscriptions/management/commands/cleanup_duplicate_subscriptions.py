from django.core.management.base import BaseCommand
from django.utils import timezone
from subscriptions.models import user_subscriptions
from django.db.models import Q


class Command(BaseCommand):
    help = 'Clean up duplicate subscriptions in the database'

    def handle(self, *args, **options):
        """
        This command removes:
        1. Duplicate active/pending subscriptions (keeps highest priority plan per user)
        2. All expired subscriptions
        """
        # Get all unique usernames with subscriptions
        usernames = user_subscriptions.objects.values_list('username', flat=True).distinct()
        
        deleted_count = 0
        updated_count = 0

        for username in usernames:
            # Get all active/pending subscriptions for this user
            subscriptions = user_subscriptions.objects.filter(
                username=username,
                status__in=['active', 'pending']
            ).order_by('subscription_type', '-start_date', '-id')

            # Group by subscription type and keep only the most recent
            seen_types = set()
            to_delete = []
            
            for sub in subscriptions:
                if sub.subscription_type in seen_types:
                    to_delete.append(sub.id)
                else:
                    seen_types.add(sub.subscription_type)

            # Delete duplicates
            if to_delete:
                deleted = user_subscriptions.objects.filter(id__in=to_delete).delete()
                deleted_count += deleted[0]

            # Delete all expired subscriptions
            expired = user_subscriptions.objects.filter(
                username=username,
                end_date__lte=timezone.now()
            ).delete()
            deleted_count += expired[0]

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully cleaned up {deleted_count} duplicate/expired subscriptions'
            )
        )
