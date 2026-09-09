"""A stable local principal for one upstream check-in identity.

**Why this exists at all.** The obvious cheap answer -- point every checked-in
request at the shared ``Makerspace.anonymous_requester`` sentinel -- is wrong here,
for four independent reasons that only show up outside the borrow-request path:

* ``PublicToolLoan.requester`` is a PROTECT FK to a real user. One sentinel makes
  every outstanding tool belong to the same fictional person, so "who has this?"
  has no answer.
* ``self_checkout_workflow`` refuses a return by anyone but the loan's requester.
  One sentinel lets any checked-in person return -- or be blamed for -- anyone's tool.
* Printer staged files are owned by ``actor.pk``, so one sentinel puts unrelated
  people in a shared upload namespace.
* ``anonymous_requester_ids()`` deliberately EXCLUDES the sentinel from
  top-borrowers and accountability, because it "is not a person: it cannot be
  contacted, cannot be ranked against real borrowers, and must never be restricted".
  Every one of those objections dissolves for a per-person principal -- and because
  that exclusion is derived from ``Makerspace.anonymous_requester_id`` alone, a
  principal created here is automatically NOT excluded. Reports and restriction
  start working with no change to either.

**Why the raw mid is stored, encrypted, rather than only hashed.** A one-way hash
cannot be reversed, and once a person checks out they leave the roster -- so name and
project would recover nothing, and an unreturned tool could never be chased. The
mapped ``mid`` is what makes an overdue borrower identifiable after they leave; the
hash column beside it is only the deterministic lookup key, mirroring
``EventRegistration.email_exact_hash``.
"""

from django.conf import settings
from django.db import models

from apps.encryption.mappers import ScopedPiiModelMixin


class CheckinIdentity(ScopedPiiModelMixin, models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="checkin_identities",
    )
    # PROTECT: the principal owns loans and requests, so deleting it out from under
    # them would orphan a chain of custody.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="checkin_identity",
    )
    # Mapped PII. The upstream member id, kept recoverable on purpose -- see the
    # module docstring.
    mid = models.TextField()
    mid_exact_hash = models.BinaryField(max_length=32, null=True, editable=False)
    mid_hash_generation = models.ForeignKey(
        "encryption.SearchKeyGeneration",
        on_delete=models.PROTECT,
        null=True,
        editable=False,
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # One principal per person per makerspace. Scoped by generation for the
            # same reason EventRegistration's is: a search-key rotation rewrites the
            # hashes, and rows from two generations must not collide during it.
            models.UniqueConstraint(
                fields=["makerspace", "mid_hash_generation", "mid_exact_hash"],
                condition=models.Q(
                    mid_hash_generation__isnull=False, mid_exact_hash__isnull=False
                ),
                name="uniq_checkin_identity_mid_hash",
            ),
            # The other half of the pair, for a deployment running with scoped-PII
            # encryption OFF: there is no search-key generation, so `mid` is stored
            # in the clear and IS directly comparable. Without this the plaintext
            # path would have no uniqueness at all and a race would mint two
            # principals for one person -- splitting their loan history in half.
            models.UniqueConstraint(
                fields=["makerspace", "mid"],
                condition=models.Q(mid_exact_hash__isnull=True),
                name="uniq_checkin_identity_mid_plain",
            ),
        ]

    def __str__(self) -> str:
        # Never the mid: __str__ reaches logs and the admin changelist, and the whole
        # point of mapping the field is that it does not land in either.
        return f"Check-in identity #{self.pk}"
