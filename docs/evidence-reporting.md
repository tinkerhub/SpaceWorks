# Evidence compliance reporting

The `evidence-compliance` report combines daily historical rollup snapshots with
unrolled evidence metadata. Evidence object expiry changes the reported object
counts without changing historical creation, attachment or recorded-byte facts.
It does not change storage-quota accounting.

## Meaning of the metrics

| Field | Meaning |
| --- | --- |
| `created_count` | Evidence metadata creations in the creation-day/type bucket, from live rows or the latest stored historical snapshot. |
| `attached_count` | Distinct evidence records attached to the existing request, return, public-loan or accountability relationships, using live rows or the stored snapshot. |
| `unattached_count` | Created minus attached, using the same live data or historical snapshot. |
| `object_expired_count` | Currently retained evidence metadata in that creation-day/type bucket with terminal `EXPIRED` retention state. |
| `object_live_count` | Created minus currently retained terminal-expired metadata. This counts references without recorded terminal expiry; actual upload and storage presence are unknown. |
| `metadata_retained_count` | Current metadata-row count for unrolled data; the recorded metadata count at snapshot time for rolled data. It is not a current retained-row census for historical buckets. |
| `bytes` | Sum of immutable recorded `size_bytes` values, treating missing sizes as zero, from live metadata or the historical snapshot. This is neither current stored bytes nor quota usage. |
| `attachment_rate_percent` | Attached divided by created, or null when created is zero. |

Only terminal `EXPIRED` counts as expired. A claimed or retrying `EXPIRING` record
continues to count toward `object_live_count`. Reports do not contact S3 or probe
either final or staging objects; even an unexpired reference may never have been
uploaded or may have missing bytes. The response's `object_count_basis` metadata
states these limitations and the historical-deletion fallback below.

## Historical rollups and expiry

Reading a rolled bucket overlays its object counts using historical
`created_count` minus the currently retained terminal-expired metadata for the
same makerspace, local creation day and evidence type. The overlay covers old
buckets beyond the seven-day rollup refresh window. It never subtracts from a
stored `object_live_count`, so rereading or rerolling does not subtract expiry
twice. It does not update old rollup revisions or append revisions during a read.

New rollup revisions snapshot the current terminal-expired and derived live
counts. Existing revision/checksum/audit behavior remains in place. Object expiry
does not change metadata rows, attachments, recorded sizes or historical rollup
facts. A report read overlays only the two object-count metrics; it keeps the
latest stored creation, attachment, metadata-count and byte snapshots.

Historical-deletion fallback is deliberately limited. Normal object retention
does not authorize metadata deletion. If separate authorized maintenance deletes
underlying metadata, an existing historical snapshot can still supply its
creation, attachment, recorded-byte and metadata-count facts. Deleting an expired
photo also cascades its retention state, so the current retained-expired total
can fall and the derived live total can rise, even after expiry was snapshotted
by rerolling. For example, a historical bucket with five creations and two
retained expired photos reports three live references. Deleting those two
metadata rows leaves five historical creations, zero retained expired photos
and five derived live references. The overlay does not preserve earlier expiry
snapshots and does not imply that any objects reappeared in storage.

## Scope, dates and report behavior

The existing report registry and makerspace/module eligibility gates still
control access. Aggregate reports retain separate `makerspace_id` rows. The
rolled expiry query is limited to one tenant and the selected rollup interval,
clipped by the cursor watermark and requested date bounds. Live and snapshot
expiry queries reuse their existing tenant/date-scoped evidence querysets.

Live creation and attachment keys, rolled bucket keys and database expiry
aggregation all use the current Django timezone's local creation day, matching
rollup day boundaries. Expiry belongs to the photo's creation bucket rather than
the day its bytes were deleted. Existing inclusive-start/exclusive-end date
filters, daily/monthly grouping, record limits, source labels and
`rollup_through` watermarks remain in effect.
