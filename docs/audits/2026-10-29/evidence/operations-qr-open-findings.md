# Operations QR source findings

Reviewer: Codex `/root/audit_backend_finish`. These are actual source traces, not executed reproductions. Source and runtime correction remain pending. No folder-wide approval follows from this packet.

## OPS-S01 — missing limits at QR input and generated-text boundaries

`operations/serializers.py` accepts an unbounded `AssetGenerateSerializer.serial_numbers` string, `QrPrintBatchCreateSerializer.title`, and `QrPrintBatchItemCreateSerializer.label_text`. Their ORM destinations are `InventoryAsset.serial_number` (100), `QrPrintBatch.title` (200), and `QrPrintBatchItem.label_text` (255). The authenticated, scoped `AssetGenerateView.post`, `QrPrintBatchListCreateView.create`, and `QrPrintBatchItemView.post` call the services/ORM without model `full_clean()`. A value one character beyond those bounds therefore reaches PostgreSQL and can raise an unhandled DataError instead of a typed validation response.

The generation service also derives a title using `f"{product.name} unit QR labels"`; a valid 200-character inventory name exceeds the title column. `name_prefix` and a legacy asset's tag can derive a label longer than its column. Fix both explicit inputs and derived display strings without truncating identifiers/serial numbers or weakening existing quota/tenancy/module guards. Real API boundary tests must prove rollback on rejected inputs and successful exact-boundary storage.

## OPS-S02 — QR mutations omit their audit event

`operations/views_qr_batches.py::AssetQrView.post` creates a QR using `get_or_create` and returns it without `audit.record`. `QrPrintBatchItemView.post` calls `services_qr_assets.add_qr_to_batch`, which can create or update an item and likewise records no event. Surrounding product generation and batch creation do log their mutation, so the missing events are specific reachable gaps. Preserve idempotent QR reprints; log an actual new QR once, and record the new/updated batch-item action transactionally with the item. The service has existing callers in generation and API code, so any actor parameter must be followed through all callers.

## OPS-S03 — control-plane printed action bypasses the module guard

`operations/admin.py::QrPrintBatchAdmin.mark_printed_selected` calls `services_qr_assets.mark_batch_printed`. That service locks the batch and checks DRAFT, but never rechecks `qr_print_batches` under the makerspace module lock. The inherited control-plane admin enforces active superuser access, hidden-makerspace scope and source gates; none adds this module guard. A retained draft batch can therefore become PRINTED while the module is disabled. Put the guard in the shared locked service, makerspace before batch, preserving the existing draft-only transition and audit.

## Review scope

The operations packet includes the actual QR services/routes/serializers/models and surrounding stocktake, transfer, container and control-plane callers. The full owner decisions and exact hashes will be captured separately. No runtime, migration, staging, commit or production mutation was performed by this reviewer.
