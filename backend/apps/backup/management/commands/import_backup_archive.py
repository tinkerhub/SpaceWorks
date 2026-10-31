from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.backup.archive_import import require_import_principal
from apps.backup.import_preflight import ImportPreflightError, validate_import_preflight
from apps.backup.services import import_disaster_archive


class Command(BaseCommand):
    help = "Register a host-supplied age archive and create its disaster restore intent."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--encrypted-file", required=True)
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--continuity-secrets", required=True)
        parser.add_argument("--expected-sha256")
        parser.add_argument("--prospective-record")

    def handle(self, *args, **options):
        try:
            preflight = validate_import_preflight(
                encrypted_file=options["encrypted_file"],
                bundle=options["bundle"],
                manifest_file=options["manifest"],
                continuity_secrets_file=options["continuity_secrets"],
                expected_sha256=options["expected_sha256"],
                require_host_support=True, prospective_record=options.get("prospective_record"),
            )
        except ImportPreflightError as exc:
            raise CommandError(str(exc)) from exc
        actor = User.objects.filter(username=options["username"]).first()
        try:
            actor = require_import_principal(actor)
            restore = import_disaster_archive(
                actor,
                options["encrypted_file"],
                preflight.manifest,
                expected_sha256=preflight.archive_sha256,
                bundle=options["bundle"], manifest_file=options["manifest"],
                continuity_secrets_file=options["continuity_secrets"],
                prospective_record=options.get("prospective_record"),
            )
        except ValidationError as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("Archive registration failed; retain the host operation evidence.") from None
        self.stdout.write(str(restore.pk))
