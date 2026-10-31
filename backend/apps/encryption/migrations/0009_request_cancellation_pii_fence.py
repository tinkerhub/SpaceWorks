"""Replace only the request trigger's watched columns; preserve historical SQL."""

from django.db import migrations


FORWARD_SQL = """
DROP TRIGGER IF EXISTS pii_fence_hardware_request_trigger ON hardware_requests_hardwarerequest;
CREATE TRIGGER pii_fence_hardware_request_trigger
BEFORE INSERT OR UPDATE OF requester_username, requester_name, requester_contact_email, requester_contact_phone, checkin_project_name, cancellation_reason
ON hardware_requests_hardwarerequest
FOR EACH ROW EXECUTE FUNCTION pii_fence_hardware_request();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS pii_fence_hardware_request_trigger ON hardware_requests_hardwarerequest;
CREATE TRIGGER pii_fence_hardware_request_trigger
BEFORE INSERT OR UPDATE OF requester_username, requester_name, requester_contact_email, requester_contact_phone, checkin_project_name
ON hardware_requests_hardwarerequest
FOR EACH ROW EXECUTE FUNCTION pii_fence_hardware_request();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("encryption", "0008_checkin_identity_pii_fence"),
        ("hardware_requests", "0026_request_cancellation"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
