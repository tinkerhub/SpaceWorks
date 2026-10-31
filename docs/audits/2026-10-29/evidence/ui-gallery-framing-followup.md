# Existing gallery framing inspection

This child could not access the parent's live CUA browser: its browser inventory
was empty and both the provided browser2/tab2 binding and iab lookup were unavailable.
No production tab, local tab, viewport, image or gallery manifest was modified.
The parent retained live capture ownership.

The pre-recapture saved images were inspected visually using the local file image viewer:

| File | Observed existing image framing |
| --- | --- |
| public-inventory.jpg | Loaded synthetic catalog and request card; public header complete. |
| public-machine-service.jpg | Loaded machine-type/filament form and footer; header complete. |
| staff-inventory.jpg | Top-left Space Works brand visible; settled inventory rows. |
| staff-requests.jpg | Top-left Space Works brand visible; settled pending/accepted requests. |
| staff-direct-handout.jpg | Brand visible; initial handout controls and empty loan state rendered. |
| staff-settings.jpg | Recapture needed: sidebar begins around Bookings; brand scrolled off. |
| staff-machines.jpg | Recapture needed: sidebar begins Inventory; brand scrolled off. |
| staff-machine-1-3d_printer.jpg | Recapture needed: sidebar begins Inventory; brand scrolled off. |
| staff-backup-restore.jpg | Recapture needed: sidebar begins Reports; brand scrolled off. |
| staff-users.jpg | Recapture needed: sidebar begins Bookings; brand scrolled off. |

These are observations of ten existing image files before parent recapture; they
are not a fresh browser or 1280×800 viewport verification. The remaining gallery
images were not silently approved. The four README images show settled content and
no observed brand-framing defect, though root may recapture them for current-source
provenance. Parent captures should reset both sidebar and document scroll, wait for
actual loaded title/data, restore the local notifications handoff, and refresh the
exact SHA-256 manifest after all saved images settle.

## Recapture closure independently inspected

Root recaptured the five named staff pages using the local browser. This child
then independently opened each current saved image with the local image viewer.
All five show the complete top-left Space Works brand, the correct Demo Makerspace
header and settled page-specific content. The printer page contains its synthetic
machine, filament pool and service queue rather than query-loading placeholders.
Settings and printer captures are full-page images; this is saved-image framing
verification, not a new browser/viewport/action-execution claim by this child.

| Current file | Saved bytes | SHA-256 |
| --- | ---: | --- |
| staff-settings.jpg | 372841 | `cc0031fe6abda2c84807854ed1f36409f1ecc8fee82d51e885246ac3d3383917` |
| staff-machines.jpg | 72846 | `4f842f49af826a52bedd78782a0eaf6020d14ed48f8864f95029a91b9e8e5f20` |
| staff-machine-1-3d_printer.jpg | 193688 | `31d07c526a5f37b17ae301644d44958e812a67d7a820d273ef5ae8c75968416f` |
| staff-backup-restore.jpg | 109454 | `22035d1e06e308f5a9be783e28f97b48b232f3445aec1c8270e96d7c9b7b7513` |
| staff-users.jpg | 61546 | `c3c479dc200e2153dca432e90cbcb7011bdf468b24e05ea9ca6798ccb917ec89` |

All **72** current manifest entries were checked against actual byte length and
SHA-256, with zero mismatches. Current manifest SHA-256:
`b756bded6429b53499a1b072142f6cb7092c189a8f49fe66b9b5f9d1b8a0867e`.
The five previously identified framing defects are closed. The other saved images
were not newly visually approved by this check; remaining public/account/detail
variants and actual recovery execution remain explicitly separate gallery limits.
No image, manifest, browser tab or application source was changed by this child.
