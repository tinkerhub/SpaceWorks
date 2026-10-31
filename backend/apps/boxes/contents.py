from apps.boxes.models import Box
from apps.inventory.models import InventoryAsset, InventoryProduct


def container_subtree_ids(makerspace, container):
    # Walk Box.parent children iteratively (Box.clean() forbids same-makerspace cycles,
    # so this terminates) to collect the container + every descendant box id, so the
    # empty-container guard sees contents nested in child boxes too.
    ids = [container.id]
    frontier = [container.id]
    while frontier:
        child_ids = list(
            Box.objects.filter(parent_id__in=frontier, makerspace=makerspace)
            .exclude(pk__in=ids)
            .values_list("id", flat=True)
        )
        if not child_ids:
            break
        ids.extend(child_ids)
        frontier = child_ids
    return ids


def box_requires_separate_contents(box):
    """Refuse implicit box checkout when contents need their own selection."""
    subtree_ids = container_subtree_ids(box.makerspace_id, box)
    return (
        InventoryAsset.objects.filter(
            makerspace_id=box.makerspace_id,
            box_id__in=subtree_ids,
            status=InventoryAsset.Status.AVAILABLE,
        ).exists()
        or InventoryProduct.objects.filter(
            makerspace_id=box.makerspace_id,
            box_id__in=subtree_ids[1:],
            is_archived=False,
            available_quantity__gt=0,
        ).exists()
    )
