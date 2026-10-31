import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.backup.import_preflight import ImportPreflightError, validate_import_preflight


class Command(BaseCommand):
    help = "Validate a host-supplied deployment archive without mutating deployment state."

    def add_arguments(self, parser):
        parser.add_argument("--encrypted-file", required=True)
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--continuity-secrets", required=True)
        parser.add_argument("--expected-sha256")
        parser.add_argument("--prospective-record")
        parser.add_argument("--restore-id", type=uuid.UUID)

    def handle(self, *args, **options):
        try:
            validate_import_preflight(
                encrypted_file=options["encrypted_file"],
                bundle=options["bundle"],
                manifest_file=options["manifest"],
                continuity_secrets_file=options["continuity_secrets"],
                expected_sha256=options["expected_sha256"],
                require_host_support=True, prospective_record=options.get("prospective_record"),
                restore_id=str(options["restore_id"]) if options.get("restore_id") is not None else None,
            )
        except ImportPreflightError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("import-preflight-ok")
