"""Set who may submit borrow requests, and report the policy that actually resulted.

Called by `setup.sh` AFTER the module tick list has been applied, never before: the
answer to "who can submit?" is only partly this flag, and the rest is the `membership`
module the operator may have just ticked. Deriving the answer from the live row is what
keeps the installer from reporting a policy the database does not have.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit import services as audit
from apps.checkin.transport import tenant_url_error
from apps.makerspaces.management.commands.list_modules import resolve_makerspace
from apps.makerspaces.request_access import (
    ACCOUNTS,
    ANYONE,
    CHECKED_IN,
    MEMBERS,
    MODE_ANYONE,
    MODE_CHECKED_IN,
    MODE_DISABLED,
    POLICY_LABELS,
    RequestAccessConflict,
    effective_policy,
    set_request_access,
)

# The operator asks for a POLICY; the column stores a MODE. `members` and `accounts`
# are the same stored mode -- which of the two you actually get is decided by the
# membership module, not by this command.
MODES = (MEMBERS, ACCOUNTS, CHECKED_IN, ANYONE)
STORED_MODE = {
    MEMBERS: MODE_DISABLED,
    ACCOUNTS: MODE_DISABLED,
    CHECKED_IN: MODE_CHECKED_IN,
    ANYONE: MODE_ANYONE,
}


class Command(BaseCommand):
    help = "Set who may submit borrow requests for a makerspace."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")
        parser.add_argument(
            "--mode",
            required=True,
            choices=MODES,
            help=(
                "members = active members only (requires the membership module); "
                "accounts = any signed-in account; "
                "checked_in = no account, verified against the upstream check-in "
                "roster (requires --checkin-space-id, and a roster URL here or in "
                "CHECKIN_API_URL); "
                "anyone = no account needed."
            ),
        )
        parser.add_argument(
            "--checkin-space-id",
            type=int,
            default=None,
            help=(
                "Bind this makerspace to an upstream check-in space id. Required "
                "before --mode checked_in, and applied before the mode is set so a "
                "single invocation can do both."
            ),
        )
        # This makerspace's own roster. Omitted leaves the stored value; an empty string
        # clears it back to the deployment default (CHECKIN_API_URL and friends).
        parser.add_argument(
            "--checkin-api-url",
            default=None,
            help="This makerspace's own roster URL (public https only). '' clears it.",
        )
        parser.add_argument(
            "--checkin-purpose",
            default=None,
            help="Required roster purpose for this makerspace. '' uses CHECKIN_REQUIRED_PURPOSE.",
        )
        parser.add_argument(
            "--checkin-provider-name",
            default=None,
            help="Check-in system name shown to borrowers. '' uses the default wording.",
        )

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        mode = options["mode"]
        updates = _roster_updates(options)
        try:
            with transaction.atomic():
                if updates:
                    # The binding, roster and mode change commit together, so a refused
                    # mode leaves the existing settings and live policy unchanged.
                    for field, value in updates.items():
                        setattr(makerspace, field, value)
                    makerspace.save(update_fields=[*updates, "updated_at"])
                    audit.record(
                        None,
                        "checkin.settings_updated",
                        makerspace=makerspace,
                        target=makerspace,
                        meta={"fields": sorted(updates), "source": "set_request_access"},
                    )
                resulting = set_request_access(makerspace, STORED_MODE[mode])
        except RequestAccessConflict as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Borrow requests for {makerspace.slug}: {POLICY_LABELS[resulting]}."
            )
        )
        if resulting != mode:
            # Never silently: asking for `members` on a space without the membership
            # module leaves submission open to any signed-in account, and an operator
            # who is not told that believes they closed something they did not.
            self.stdout.write(
                self.style.WARNING(
                    f"You asked for '{mode}' but the live module state produces "
                    f"'{resulting}'. "
                    + (
                        "Install the `membership` module to restrict submission to "
                        "members."
                        if resulting == ACCOUNTS
                        else "Uninstall the `membership` module to allow account-less "
                        "requests."
                    )
                )
            )
        return None


def _roster_updates(options):
    updates = {}
    if options["checkin_space_id"] is not None:
        updates["checkin_space_id"] = options["checkin_space_id"]
    url = options["checkin_api_url"]
    if url is not None:
        url = url.strip()
        # Same outbound guard as the console: a URL saved here is fetched by the server.
        error = tenant_url_error(url) if url else ""
        if error:
            raise CommandError(f"--checkin-api-url: {error}")
        if len(url) > 500:
            raise CommandError("--checkin-api-url: at most 500 characters.")
        updates["checkin_api_url"] = url
    for option, field, limit in (
        ("checkin_purpose", "checkin_required_purpose", 200),
        ("checkin_provider_name", "checkin_provider_name", 100),
    ):
        value = options[option]
        if value is not None:
            value = value.strip()
            if len(value) > limit:
                raise CommandError(f"--{option.replace('_', '-')}: at most {limit} characters.")
            updates[field] = value
    return updates


def current_policy(makerspace) -> str:
    """Shared with the installer's read-back step."""
    return effective_policy(makerspace)
