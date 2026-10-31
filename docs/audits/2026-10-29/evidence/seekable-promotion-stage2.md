# Seekable promotion: bounded Stage2 source implementation

Authorization: `/tmp/spaceworks-seekable-promotion-plan.md`, independently
`APPROVED` in `/tmp/spaceworks-seekable-promotion-plan-review.txt`, and the
parent's explicit four-source-file authorization. This note records Stage2 only.

## Source behavior

`storage_promotion.create_final_from_staging` validates supplied size/SHA facts
before opening the source or creating a spool. Both facts must be supplied
together: an exact nonnegative `int` size (excluding `bool`) and a canonical
64-character lowercase hexadecimal SHA-256 string. Invalid facts raise the
existing `BackupVerificationError` subtype.

The source remains a nonseekable SDK streaming body. Reads request at most
`min(CHUNK_SIZE, remaining + 1)` bytes, with `CHUNK_SIZE` unchanged at 1 MiB.
An oversized chunk is rejected before writing it to disk. A private, unlinked
`tempfile.TemporaryFile(mode="w+b")` holds the bounded archive. Exact observed
size and the supplied SHA-256 must match before any final PUT. The spool is
rewound and passed as the seekable `Body`, with observed `ContentLength`, the
existing `application/octet-stream` content type, and `IfNoneMatch="*"`.
Default SDK checksum behavior is unchanged.

The unused two-argument `storage.copy_archive` compatibility path remains
bounded: when both expected facts are absent, source GET `ContentLength` must
be an exact nonnegative integer. Missing or malformed length refuses before
spooling and closes the source. This path calculates SHA-256 but makes no
authenticated expected-hash claim. No extra HEAD or ORM lookup was added.

All three real callers now pass both known facts:

- `artifact_protocol.py`: `ledger.expected_size_bytes`, `ledger.outer_sha256`.
- `reconciliation.py`: `row.expected_size_bytes`, `row.outer_sha256`.
- `services_archives.py`: captured `size`, `archive_sha256`.

Existing staging/final whole-GET verification, ledger compare-and-swap
promotion, and remote cleanup remain unchanged. Promotion adds no remote
deletion, overwrite/copy fallback, multipart framework, or checksum override.
SDK and filesystem errors map to the existing fixed `BackupStorageError`
messages; conditional-conflict handling is preserved. Both handles receive a
close attempt on success and failure. SDK/filesystem close errors do not mask
a primary failure; a close failure after successful PUT becomes a fixed typed
storage error. Verification failures retain their subtype.

The pre-existing reconciliation operation-lock changes were preserved. Other
writers' test-only Docker-boundary work was not edited.

## Static verification and whole-file identity

Only source text inspection, stdlib AST parsing, line counting, SHA-256 hashing,
and scoped `git diff --check` were used. AST checks covered the bounded read,
disk tempfile mode, rewind, seekable PUT body and explicit content length,
create-only/content-type headers, absence of new HEAD/copy/delete operations
or checksum overrides, and expected-fact kwargs at each of the three callers.
These checks passed; they are not runtime or SDK execution evidence.

Hashes below cover complete current source bytes, including pre-existing edits,
and are an implementation identity record, not an update to a source freeze.

| Source path | Lines | Whole-file SHA-256 |
| --- | ---: | --- |
| `backend/apps/backup/storage_promotion.py` | 176 | `a944b057138fd2510357665a548a2c2126eea6f61f7759573727de4089e4b4a3` |
| `backend/apps/backup/artifact_protocol.py` | 37 | `2e65e2c5b76bfebe73cc9e467e43a369b44ebd2f7e075edfc1d77a5521781fe2` |
| `backend/apps/backup/reconciliation.py` | 140 | `bdaf87285bec7cfd62622097e5871d9b2ec96e34f65d102239af7d679677535c` |
| `backend/apps/backup/services_archives.py` | 263 | `b02860b19d6c02af9eb2e6685abaef95b36558bce7e2a9103a7328caba1b530f` |

No tests were written or run. No project imports, collection, database access,
Docker, builds, runtime actions, private worker-log/credential inspection,
staging, or commits were performed. Shared docs, historical source/test freezes,
and the 25-path guard were not edited. Stage3 and later review/runtime gates
remain parent-owned, including actual SDK StreamingBody/default-checksum proof.

Before another genuine isolated producer attempt, the parent must deliberately
update the source freeze to include these four paths and freeze the Stage3 test
bytes, build a new genuine OCI artifact, restart both backend and worker on that
artifact, and run a new actual backup. Existing failed-archive evidence remains
untouched; these source edits establish no successful backup or restore claim.

## Operator paragraph for parent-owned self-hosting documentation

Backup publication needs local temporary-disk headroom for an additional full
encrypted archive while staging is verified, alongside the build's existing
temporary files. Provide adequate space in the worker's temporary directory.
The encrypted bytes are spooled to a private, unlinked disk tempfile and its
handle is closed on success or failure; bounded chunks keep memory use limited.
Disk exhaustion fails publication through the typed storage-error path. No SQL
restore was performed by this Stage2 work; the reported producer failure occurred
before restore.
