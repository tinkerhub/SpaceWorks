from django.db.models import Sum

from apps.machines.models import Machine
from apps.machines.usage_totals import annotate_machine_usage
from apps.makerspaces.platform import module_enabled


def build_public_machine_stats(makerspace):
    if not module_enabled(makerspace, 'machines'):
        return None
    machines = Machine.objects.filter(
        makerspace=makerspace,
        is_public=True,
        is_active=True,
    )
    total = annotate_machine_usage(machines).aggregate(total=Sum('usage_total'))['total']
    return {'usage_hours': round(float(total or 0), 2)}
