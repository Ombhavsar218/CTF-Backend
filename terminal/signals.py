"""Close gateway sessions as soon as Stage 1C retires an instance."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from instances.models import ChallengeInstance

from .services import SessionRegistry


@receiver(post_save, sender=ChallengeInstance)
def revoke_terminal_state_on_instance_status(sender, instance, **kwargs):
    if instance.status in {
        ChallengeInstance.STATUS_STOPPING,
        ChallengeInstance.STATUS_STOPPED,
        ChallengeInstance.STATUS_EXPIRED,
        ChallengeInstance.STATUS_FAILED,
    }:
        SessionRegistry.revoke_for_instance(
            instance, reason=f'instance_{instance.status}'
        )
