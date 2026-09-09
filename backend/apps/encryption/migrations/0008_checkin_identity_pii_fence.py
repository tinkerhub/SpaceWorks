"""Write fence for the check-in identity's mapped mid.

Same shape as `0006_machine_service_request_pii_fence`. The historical `0004` trigger
is not edited: it names the four HardwareRequest columns and must keep doing so.
A new mapped model needs its own trigger, or an INSERT of an encrypted envelope could
land without the tenant's mapped-write assertion having run.
"""

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION pii_fence_checkin_identity() RETURNS trigger AS $$
BEGIN
  PERFORM pii_assert_mapped_write_allowed(NEW.makerspace_id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pii_fence_checkin_identity_trigger
BEFORE INSERT OR UPDATE OF mid
ON checkin_checkinidentity
FOR EACH ROW EXECUTE FUNCTION pii_fence_checkin_identity();

-- HardwareRequest gains a fifth mapped column. The trigger names its watched columns
-- explicitly, so it must be REPLACED rather than left alone: INSERTs were already
-- fenced, but an UPDATE touching only `checkin_project_name` would otherwise write an
-- envelope with the tenant's mapped-write assertion never having run. Historical
-- migration 0004 is not edited -- it is replayed as written on a fresh database, and
-- this replaces its trigger afterwards.
DROP TRIGGER IF EXISTS pii_fence_hardware_request_trigger ON hardware_requests_hardwarerequest;
CREATE TRIGGER pii_fence_hardware_request_trigger
BEFORE INSERT OR UPDATE OF requester_username, requester_name, requester_contact_email, requester_contact_phone, checkin_project_name
ON hardware_requests_hardwarerequest
FOR EACH ROW EXECUTE FUNCTION pii_fence_hardware_request();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS pii_fence_checkin_identity_trigger ON checkin_checkinidentity;
DROP FUNCTION IF EXISTS pii_fence_checkin_identity();

-- Restore 0004's column list exactly.
DROP TRIGGER IF EXISTS pii_fence_hardware_request_trigger ON hardware_requests_hardwarerequest;
CREATE TRIGGER pii_fence_hardware_request_trigger
BEFORE INSERT OR UPDATE OF requester_username, requester_name, requester_contact_email, requester_contact_phone
ON hardware_requests_hardwarerequest
FOR EACH ROW EXECUTE FUNCTION pii_fence_hardware_request();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("encryption", "0007_tenant_import_fence_operation"),
        ("checkin", "0001_initial"),
        ("hardware_requests", "0025_checkin_provenance"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
