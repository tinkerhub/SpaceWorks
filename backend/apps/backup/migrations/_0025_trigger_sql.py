"""Frozen installer trigger refuses disabled and same-name incorrect guards."""

SQL = r"""
CREATE OR REPLACE FUNCTION public.backup_b1_install_reservation_trigger() RETURNS trigger AS $$
DECLARE
  target_schema text;
  target_table text;
  target_oid regclass;
BEGIN
  IF NEW.installed_at IS NULL THEN
    RETURN NEW;
  END IF;
  target_schema := COALESCE(
    NEW.safe_payload->>'schema', NEW.safe_payload->'enforcement'->>'schema', 'public'
  );
  target_table := COALESCE(
    NEW.safe_payload->>'table', NEW.safe_payload->'enforcement'->>'table'
  );
  IF target_table IS NULL THEN
    RAISE EXCEPTION 'installed reservation lacks a target table';
  END IF;
  target_oid := to_regclass(format('%I.%I', target_schema, target_table));
  IF target_oid IS NULL THEN
    RAISE EXCEPTION 'installed reservation target %.% does not exist', target_schema, target_table;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
     WHERE tgrelid = target_oid AND tgname = 'backup_b1_reservation_guard'
       AND NOT tgisinternal
  ) THEN
    EXECUTE format(
      'CREATE TRIGGER backup_b1_reservation_guard '
      'BEFORE INSERT OR UPDATE OR DELETE ON %I.%I '
      'FOR EACH ROW EXECUTE FUNCTION public.backup_b1_enforce_reservations()',
      target_schema, target_table
    );
  END IF;
  IF public.backup_b1_live_guard(target_oid::oid,
    to_regprocedure('public.backup_b1_enforce_reservations()')::oid) IS NULL THEN
    RAISE EXCEPTION 'existing reservation trigger has an unsafe structure or enabled mode';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;
"""

REVERSE = r"""
CREATE OR REPLACE FUNCTION public.backup_b1_install_reservation_trigger() RETURNS trigger AS $$
DECLARE
  target_schema text;
  target_table text;
  target_oid regclass;
BEGIN
  IF NEW.installed_at IS NULL THEN
    RETURN NEW;
  END IF;
  target_schema := COALESCE(
    NEW.safe_payload->>'schema', NEW.safe_payload->'enforcement'->>'schema', 'public'
  );
  target_table := COALESCE(
    NEW.safe_payload->>'table', NEW.safe_payload->'enforcement'->>'table'
  );
  IF target_table IS NULL THEN
    RAISE EXCEPTION 'installed reservation lacks a target table';
  END IF;
  target_oid := to_regclass(format('%I.%I', target_schema, target_table));
  IF target_oid IS NULL THEN
    RAISE EXCEPTION 'installed reservation target %.% does not exist', target_schema, target_table;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
     WHERE tgrelid = target_oid AND tgname = 'backup_b1_reservation_guard'
       AND NOT tgisinternal
  ) THEN
    EXECUTE format(
      'CREATE TRIGGER backup_b1_reservation_guard '
      'BEFORE INSERT OR UPDATE OR DELETE ON %I.%I '
      'FOR EACH ROW EXECUTE FUNCTION backup_b1_enforce_reservations()',
      target_schema, target_table
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;
"""
