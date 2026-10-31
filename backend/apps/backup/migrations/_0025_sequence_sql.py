"""Frozen 0025 signed sequence shape and actual monotonic frontier proof."""

SQL = r"""
CREATE FUNCTION public.backup_b1_sequence_shape(f jsonb) RETURNS boolean AS $$
DECLARE k text;
BEGIN
  IF NOT public.backup_b1_exact_keys(f, ARRAY[
    'schema','sequence','table','column','type_identity','increment','start',
    'minimum','maximum','cycle','cache','captured_last_value','captured_is_called',
    'installed_last_value','installed_is_called','next_generated_value',
    'constraint_identity','definition_sha256'
  ]) THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['schema','sequence','table','column','type_identity'] LOOP
    IF jsonb_typeof(f->k) IS DISTINCT FROM 'string' OR f->>k = '' THEN
      RETURN false;
    END IF;
  END LOOP;
  FOREACH k IN ARRAY ARRAY['increment','start','minimum','maximum','cache',
    'captured_last_value','installed_last_value','next_generated_value'] LOOP
    IF jsonb_typeof(f->k) IS DISTINCT FROM 'number'
       OR (f->>k) !~ '^-?[0-9]+$' THEN RETURN false; END IF;
    -- Signed sequence storage is PostgreSQL bigint, never arbitrary numeric.
    PERFORM (f->>k)::bigint;
  END LOOP;
  IF jsonb_typeof(f->'captured_is_called') IS DISTINCT FROM 'boolean'
     OR f->'installed_is_called' IS DISTINCT FROM 'true'::jsonb
     OR f->'cycle' IS DISTINCT FROM 'false'::jsonb
     OR (f->>'increment')::numeric = 0 OR (f->>'cache')::numeric <= 0
     OR NOT (f->>'start')::numeric BETWEEN
       (f->>'minimum')::numeric AND (f->>'maximum')::numeric
     OR NOT (f->>'captured_last_value')::numeric BETWEEN
       (f->>'minimum')::numeric AND (f->>'maximum')::numeric
     OR NOT (f->>'installed_last_value')::numeric BETWEEN
       (f->>'minimum')::numeric AND (f->>'maximum')::numeric
     OR (f->>'next_generated_value')::numeric <>
       (f->>'installed_last_value')::numeric + (f->>'increment')::numeric
     OR NOT (f->>'next_generated_value')::numeric BETWEEN
       (f->>'minimum')::numeric AND (f->>'maximum')::numeric THEN RETURN false;
  END IF;
  IF jsonb_typeof(f->'constraint_identity') IS DISTINCT FROM 'string'
     OR jsonb_typeof(f->'definition_sha256') IS DISTINCT FROM 'string'
     OR NOT ((f->>'constraint_identity' = '' AND f->>'definition_sha256' = '')
       OR (f->>'constraint_identity' ~ '^[0-9a-f]{64}$'
           AND f->>'definition_sha256' ~ '^[0-9a-f]{64}$')) THEN RETURN false;
  END IF;
  RETURN true;
END;
$$ LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, public;

CREATE FUNCTION public.backup_b1_prove_sequences(facts jsonb) RETURNS boolean AS $$
DECLARE
  f jsonb;
  actual record;
  last_stored numeric;
  called boolean;
  occupied numeric;
  next_frontier numeric;
  step numeric;
  seen text[] := ARRAY[]::text[];
  sequence_key text;
  actual_keys text[];
BEGIN
  IF jsonb_typeof(facts) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  FOR f IN SELECT value FROM jsonb_array_elements(facts) LOOP
    IF NOT public.backup_b1_sequence_shape(f) THEN RETURN false; END IF;
    sequence_key := format('%I.%I', f->>'schema', f->>'sequence');
    IF sequence_key = ANY(seen) THEN RETURN false; END IF;
    seen := array_append(seen, sequence_key);
    SELECT s.*, tbl.relname AS owner_table, tn.nspname AS owner_schema,
           attr.attname AS owner_column,
           typns.nspname || '.' || typ.typname || ':' ||
             pg_catalog.format_type(attr.atttypid, attr.atttypmod) AS type_identity
      INTO actual
      FROM pg_catalog.pg_sequence s
      JOIN pg_catalog.pg_class seq ON seq.oid=s.seqrelid
      JOIN pg_catalog.pg_namespace ns ON ns.oid=seq.relnamespace
      JOIN pg_catalog.pg_depend dep ON dep.objid=seq.oid AND dep.deptype IN ('a','i')
        AND dep.classid='pg_catalog.pg_class'::regclass
        AND dep.refclassid='pg_catalog.pg_class'::regclass
      JOIN pg_catalog.pg_class tbl ON tbl.oid=dep.refobjid
      JOIN pg_catalog.pg_namespace tn ON tn.oid=tbl.relnamespace
      JOIN pg_catalog.pg_attribute attr ON attr.attrelid=tbl.oid
        AND attr.attnum=dep.refobjsubid AND NOT attr.attisdropped
      JOIN pg_catalog.pg_type typ ON typ.oid=attr.atttypid
      JOIN pg_catalog.pg_namespace typns ON typns.oid=typ.typnamespace
     WHERE ns.nspname=f->>'schema' AND seq.relname=f->>'sequence';
    IF NOT FOUND THEN RETURN false; END IF;
    IF actual.owner_table IS DISTINCT FROM f->>'table'
       OR actual.owner_schema IS DISTINCT FROM f->>'schema'
       OR actual.owner_column IS DISTINCT FROM f->>'column'
       OR actual.type_identity IS DISTINCT FROM f->>'type_identity'
       OR actual.seqincrement <> (f->>'increment')::bigint
       OR actual.seqstart <> (f->>'start')::bigint
       OR actual.seqmin <> (f->>'minimum')::bigint
       OR actual.seqmax <> (f->>'maximum')::bigint
       OR actual.seqcycle OR actual.seqcache <> (f->>'cache')::bigint THEN
      RETURN false;
    END IF;
    -- Read persisted storage, never the producer's computed recommended value.
    EXECUTE format('SELECT last_value::numeric, is_called FROM %I.%I',
      f->>'schema', f->>'sequence') INTO STRICT last_stored, called;
    step := actual.seqincrement;
    IF called IS NOT TRUE OR NOT last_stored BETWEEN actual.seqmin AND actual.seqmax
       OR (step > 0 AND last_stored < (f->>'installed_last_value')::numeric)
       OR (step < 0 AND last_stored > (f->>'installed_last_value')::numeric) THEN
      RETURN false;
    END IF;
    next_frontier := last_stored + step;
    IF NOT next_frontier BETWEEN actual.seqmin AND actual.seqmax THEN RETURN false; END IF;
    EXECUTE format('SELECT %s(%I)::numeric FROM %I.%I',
      CASE WHEN step > 0 THEN 'max' ELSE 'min' END, f->>'column',
      actual.owner_schema, actual.owner_table) INTO occupied;
    IF occupied IS NOT NULL AND (
      (step > 0 AND next_frontier <= occupied) OR (step < 0 AND next_frontier >= occupied)
    ) THEN RETURN false; END IF;
  END LOOP;
  SELECT COALESCE(array_agg(format('%I.%I', ns.nspname, seq.relname)
    ORDER BY format('%I.%I', ns.nspname, seq.relname)), ARRAY[]::text[])
    INTO actual_keys FROM pg_catalog.pg_sequence s
    JOIN pg_catalog.pg_class seq ON seq.oid=s.seqrelid
    JOIN pg_catalog.pg_namespace ns ON ns.oid=seq.relnamespace
    JOIN pg_catalog.pg_depend dep ON dep.objid=seq.oid AND dep.deptype IN ('a','i')
      AND dep.classid='pg_catalog.pg_class'::regclass
      AND dep.refclassid='pg_catalog.pg_class'::regclass
    WHERE ns.nspname='public';
  RETURN actual_keys = ARRAY(SELECT unnest(seen) ORDER BY 1);
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""
