from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models_common import (
    generate_domain_verification_token,
    generate_public_code,
    generate_publishable_key,
    normalize_frontend_domain,
    presence_presets,
)
from apps.makerspaces.module_registry import default_enabled_module_keys


# Derived from the module registry -- kept as a module-level name because the
# /control/ form and several tests import it. Add a module in module_registry.py.
DEFAULT_ENABLED_MODULES = default_enabled_module_keys()


def default_enabled_modules():
    # Referenced by migration 0009 as a JSONField default, so this import path is
    # load-bearing and must keep resolving. Returns a fresh list every call.
    return default_enabled_module_keys()


def default_theme_config():
    return {
        "mode": "light",
        "primary_color": "#2563eb",
        "accent_color": "#16a34a",
        "logo_url": "",
    }


def default_branding_config():
    return {
        "display_name": "",
        "support_email": "",
        "support_url": "",
    }


from apps.makerspaces.models_makerspace import Makerspace  # noqa: E402,F401
from apps.makerspaces.models_memberships import MakerspaceMembership  # noqa: E402,F401
from apps.makerspaces.models_roles import (  # noqa: E402,F401
    MakerspaceRole,
    MakerspaceWaiver,
    MembershipRequest,
    SubdomainRequest,
)
from apps.makerspaces.models_profiles import (  # noqa: E402,F401
    MemberProfile,
    MemberProject,
)
from apps.makerspaces.models_archive_requests import (  # noqa: E402,F401
    MakerspaceArchiveRequest,
)
from apps.makerspaces.models_imports import (  # noqa: E402,F401
    ImportedUserReconciliation,
    PendingImportedMembership,
)
