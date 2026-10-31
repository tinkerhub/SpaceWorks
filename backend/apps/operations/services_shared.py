from django.shortcuts import get_object_or_404

from apps.boxes.models import Box


def _container(container_id, makerspace_id):
    if not container_id:
        return None
    return get_object_or_404(Box, pk=container_id, makerspace_id=makerspace_id)
