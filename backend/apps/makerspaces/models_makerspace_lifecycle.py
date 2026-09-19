"""`Makerspace.save()` and `Makerspace.clean()` — normalisation and cross-field validation.

Split out of `models_makerspace.py` so that file stays under the repo's ~300-line
ceiling, following the same rule as `models_makerspace_secrets`: this module carries
**no field definitions**, only behaviour, so moving it changes no schema and needs no
migration.

It is a mixin rather than module-level helpers because both methods are overrides —
`save()` chains to `models.Model.save()` through `super()`, which only works from
inside the MRO.
"""

from django.core.exceptions import ValidationError

from apps.makerspaces.capabilities import prune_features, validate_capabilities
from apps.makerspaces.models_common import normalize_frontend_domain
from apps.makerspaces.request_access import reconcile_mode
from apps.makerspaces.validators import validate_presence_presets


class MakerspaceLifecycleMixin:
    """Write-path normalisation and validation for `Makerspace`."""

    def save(self, *args, **kwargs):
        self.public_code = (self.public_code or "").upper()
        self.frontend_domain = normalize_frontend_domain(self.frontend_domain)
        # Membership and account-less requests are mutually exclusive, and this is the
        # ONE chokepoint every writer passes through: module install/uninstall, profile
        # application, the /control/ capability matrix, setup_instance, seed_demo and a
        # plain obj.save(). Enforcing it here rather than in each of them is what makes
        # the state unreachable instead of merely discouraged -- see
        # `request_access` for why the pair is impossible.
        reconciled = reconcile_mode(self.enabled_modules, self.public_request_mode)
        if reconciled != self.public_request_mode:
            self.public_request_mode = reconciled
            # A partial save that did not name this field would otherwise change the
            # attribute in memory and leave the row in the impossible state.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "public_request_mode"]
        super().save(*args, **kwargs)

    def clean(self):
        if self.presence_preset_minutes:
            validate_presence_presets(self.presence_preset_minutes)
        # Drop features whose module is not in this row's set BEFORE validating. The
        # module set is authoritative — `_canonical_modules` already normalizes rather
        # than rejects (it adds core keys back), and this is the same class of
        # normalization on the other axis.
        #
        # Without it a row can be born invalid and then never saved again: creating a
        # makerspace with a narrow `enabled_modules` still takes the FIELD default for
        # `enabled_features`, which includes the default-on `payments.enabled` and
        # `mobile.push`. Those demand modules the row does not have, so `clean()` raised
        # on every subsequent save — including saves that touched neither field, such as
        # a Space Manager toggling public stats.
        #
        # The user-facing strictness is unaffected: the `/control/` capability matrix and
        # `module_install` call `validate_capabilities` directly before saving, so a
        # conflict the operator actually expressed is still reported there rather than
        # silently cleared.
        kept, _dropped = prune_features(
            self.enabled_features or [], self.enabled_modules or []
        )
        self.enabled_modules, self.enabled_features = validate_capabilities(
            self.enabled_modules or [], kept
        )
        if self.hidden_from_central_directory and not self.frontend_domain:
            raise ValidationError(
                {
                    "hidden_from_central_directory": (
                        "A frontend domain is required to hide a makerspace from the central directory."
                    )
                }
            )
        if self.geofence_enabled and not self.geofence_effective:
            raise ValidationError({"geofence_enabled": "Set both latitude and longitude before enabling the geofence."})
