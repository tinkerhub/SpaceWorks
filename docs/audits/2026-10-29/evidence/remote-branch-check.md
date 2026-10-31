# Remote branch inventory

Fresh `git fetch origin --prune` completed during the audit continuation. This is an inventory, not a deletion record.

| Ref | Observed tip | Disposition |
| --- | --- | --- |
| `origin/main` | `86ac8b5f60b5c3ba5b8f1bed85ddb23cb707b0fb` | Preserve release branch. |
| `origin/dev` | `90ae2d5e911fcd18a35367d13fa1c2db346e2f0f` | Preserve development branch, even though merged into main. |
| `origin/fix` | `15fbc3658ff8a2422c97df4801df0cacabd0b9c2` | Ancestor of origin/main; candidate for the owner's requested merged-branch cleanup after audit. Re-fetch and recheck exact tip before deletion. |

Local `dev` is `1aadf4752b92517349f28cb1cae7543acf38006c`, one local commit ahead of origin/dev. Current audit changes are uncommitted. No remote branches have been deleted in this continuation.
