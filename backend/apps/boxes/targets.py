"""Resolve generic QR targets without crossing their makerspace boundary."""

from django.http import Http404
from django.shortcuts import get_object_or_404

from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct


def qr_target(qr):
    model = {
        QrCode.TargetType.BOX: Box,
        QrCode.TargetType.PRODUCT: InventoryProduct,
        QrCode.TargetType.ASSET: InventoryAsset,
    }.get(qr.target_type)
    if model is None:
        raise Http404("QR target not found.")
    queryset = model.objects.all()
    if model is InventoryAsset:
        # This is an unlocked read; no nullable joined row is locked.
        queryset = queryset.select_related("product")
    return get_object_or_404(queryset, pk=qr.target_id, makerspace_id=qr.makerspace_id)
