from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION events_guard_certificate_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.allow_immutable_delete', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'immutable certificate delete not allowed';
    END IF;
    IF NEW.response_id IS DISTINCT FROM OLD.response_id OR
       NEW.registration_id IS DISTINCT FROM OLD.registration_id OR
       NEW.serial IS DISTINCT FROM OLD.serial OR
       NEW.revision IS DISTINCT FROM OLD.revision OR
       NEW.recipient_name IS DISTINCT FROM OLD.recipient_name OR
       NEW.event_title IS DISTINCT FROM OLD.event_title OR
       NEW.event_starts_at IS DISTINCT FROM OLD.event_starts_at OR
       NEW.event_ends_at IS DISTINCT FROM OLD.event_ends_at OR
       NEW.issuer_name IS DISTINCT FROM OLD.issuer_name OR
       NEW.object_key IS DISTINCT FROM OLD.object_key OR
       NEW.content_type IS DISTINCT FROM OLD.content_type OR
       NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
        RAISE EXCEPTION 'certificate issuance snapshots are immutable';
    END IF;
    IF (OLD.status = 'active' OR OLD.rendered_at IS NOT NULL OR OLD.size_bytes IS NOT NULL) AND (
        NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
        NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
        NEW.rendered_at IS DISTINCT FROM OLD.rendered_at
    ) THEN
        RAISE EXCEPTION 'active certificate artifact is immutable';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status IN ('pending', 'failed') AND NEW.status IN ('rendering', 'revoked')) OR
        (OLD.status = 'rendering' AND NEW.status IN ('active', 'failed', 'revoked')) OR
        (OLD.status = 'active' AND NEW.status = 'revoked')
    ) THEN
        RAISE EXCEPTION 'invalid certificate status transition: % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;
"""

REVERSE_SQL = """
CREATE OR REPLACE FUNCTION events_guard_certificate_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.allow_immutable_delete', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'immutable certificate delete not allowed';
    END IF;
    IF NEW.response_id IS DISTINCT FROM OLD.response_id OR
       NEW.registration_id IS DISTINCT FROM OLD.registration_id OR
       NEW.serial IS DISTINCT FROM OLD.serial OR
       NEW.revision IS DISTINCT FROM OLD.revision OR
       NEW.recipient_name IS DISTINCT FROM OLD.recipient_name OR
       NEW.event_title IS DISTINCT FROM OLD.event_title OR
       NEW.event_starts_at IS DISTINCT FROM OLD.event_starts_at OR
       NEW.event_ends_at IS DISTINCT FROM OLD.event_ends_at OR
       NEW.issuer_name IS DISTINCT FROM OLD.issuer_name OR
       NEW.object_key IS DISTINCT FROM OLD.object_key OR
       NEW.content_type IS DISTINCT FROM OLD.content_type OR
       NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
        RAISE EXCEPTION 'certificate issuance snapshots are immutable';
    END IF;
    IF OLD.status = 'active' AND (
        NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
        NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
        NEW.rendered_at IS DISTINCT FROM OLD.rendered_at
    ) THEN
        RAISE EXCEPTION 'active certificate artifact is immutable';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status IN ('pending', 'failed') AND NEW.status = 'rendering') OR
        (OLD.status = 'rendering' AND NEW.status IN ('active', 'failed')) OR
        (OLD.status = 'active' AND NEW.status = 'revoked')
    ) THEN
        RAISE EXCEPTION 'invalid certificate status transition: % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0021_offline_and_station_checkin"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
