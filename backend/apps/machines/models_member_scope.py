"""Machine types one staff member reaches on top of their role's links.

Role links (``models_role_scope``) are the team-sized unit, but a lab often has one person
who runs the lasers and one who runs the printers under the same role. Without a
per-person link that needs a role per person, which is exactly the role sprawl the
editable-role model was meant to avoid.

A personal link only WIDENS the reach of a ``MANAGE_MACHINES`` grant the member's role
already holds; it never grants the action. ``rbac.can`` is untouched, so a member whose
role lacks the Machines capability gains nothing from a personal link, and a member whose
role has it but no type links reaches exactly their personal types and nothing else.

Resolution (``role_scope_resolution``) unions these rows into the role's type set, so every
surface that already honours role scoping -- lists, actions, dashboards, notification
recipients -- picks them up with no change of its own.
"""

from django.core.exceptions import ValidationError
from django.db import models


class MembershipMachineTypeScope(models.Model):
    """Grants one membership's ``MANAGE_MACHINES`` reach over every machine of one type."""

    membership = models.ForeignKey(
        "makerspaces.MakerspaceMembership",
        on_delete=models.CASCADE,
        related_name="machine_type_scopes",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="membership_scopes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "machine_type"], name="membershipmachinetypescope_uniq"
            ),
        ]

    def __str__(self):
        return f"membership {self.membership_id} -> type {self.machine_type_id}"

    def clean(self):
        """Reject a link across makerspaces. A global built-in type is always allowed."""
        machine_type = self.machine_type
        if machine_type.makerspace_id is None:
            return
        if machine_type.makerspace_id != self.membership.makerspace_id:
            raise ValidationError(
                {"machine_type": "A member can only be scoped to their own makerspace's machine types."}
            )
