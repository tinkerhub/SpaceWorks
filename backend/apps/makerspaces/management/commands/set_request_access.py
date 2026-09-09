"""Set who may submit borrow requests, and report the policy that actually resulted.

Called by `setup.sh` AFTER the module tick list has been applied, never before: the
answer to "who can submit?" is only partly this flag, and the rest is the `membership`
module the operator may have just ticked. Deriving the answer from the live row is what
keeps the installer from reporting a policy the database does not have.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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
                "roster (requires --checkin-space-id to have been set); "
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

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        mode = options["mode"]
        space_id = options["checkin_space_id"]
        try:
            with transaction.atomic():
                if space_id is not None:
                    # The binding and mode change commit together, so a refused mode
                    # leaves the existing binding and live policy unchanged.
                    makerspace.checkin_space_id = space_id
                    makerspace.save(update_fields=["checkin_space_id"])
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


def current_policy(makerspace) -> str:
    """Shared with the installer's read-back step."""
    return effective_policy(makerspace)
