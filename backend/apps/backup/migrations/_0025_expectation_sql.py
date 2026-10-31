"""Frozen 0025 canonical UTF-8 expectation schema, independent of runtime code."""

SQL = r"""
CREATE FUNCTION public.backup_b1_canonical_json(value jsonb) RETURNS text AS $$
DECLARE result text;
BEGIN
  CASE jsonb_typeof(value)
    WHEN 'object' THEN
      SELECT '{' || COALESCE(string_agg(to_jsonb(key)::text || ':' ||
        public.backup_b1_canonical_json(val), ',' ORDER BY key COLLATE "C"), '') || '}'
        INTO result FROM jsonb_each(value) AS item(key, val);
    WHEN 'array' THEN
      SELECT '[' || COALESCE(string_agg(public.backup_b1_canonical_json(val), ','
        ORDER BY ordinal), '') || ']' INTO result
        FROM jsonb_array_elements(value) WITH ORDINALITY AS item(val, ordinal);
    ELSE result := value::text;
  END CASE;
  RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog, public;

CREATE FUNCTION public.backup_b1_exact_keys(value jsonb, keys text[])
RETURNS boolean AS $$
  SELECT jsonb_typeof(value) = 'object' AND
    ARRAY(SELECT jsonb_object_keys(value) ORDER BY 1) =
    ARRAY(SELECT unnest(keys) ORDER BY 1);
$$ LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public;

CREATE FUNCTION public.backup_b1_expected_inventory(
  operation public.backup_b1restoreoperationstate
) RETURNS jsonb AS $$
DECLARE
  expected jsonb;
  component jsonb;
  entry jsonb;
  fact jsonb;
  payload jsonb;
  sequence_fact jsonb;
  identities text[] := ARRAY[]::text[];
  entry_keys text[] := ARRAY[]::text[];
  sequence_keys text[] := ARRAY[]::text[];
  key text;
  previous_key text := '';
  shared jsonb := '{}'::jsonb;
  signature jsonb;
  target_schema text;
  target_table text;
BEGIN
  IF operation.expected_installation = '' OR operation.expected_installation_sha256 = '' THEN
    RAISE EXCEPTION 'legacy unfinished restore is unattested; start a fresh restore';
  END IF;
  IF operation.expected_installation_sha256 !~ '^[0-9a-f]{64}$'
     OR encode(sha256(convert_to(operation.expected_installation, 'UTF8')), 'hex') <>
       operation.expected_installation_sha256 THEN
    RAISE EXCEPTION 'expected installation text digest is invalid';
  END IF;
  expected := operation.expected_installation::jsonb;
  IF public.backup_b1_canonical_json(expected) IS DISTINCT FROM operation.expected_installation
     OR NOT public.backup_b1_exact_keys(expected,
       ARRAY['version','manifest_sha256','components','entries','sequences'])
     OR expected->'version' IS DISTINCT FROM '1'::jsonb
     OR expected->>'version' IS DISTINCT FROM '1'
     OR jsonb_typeof(expected->'manifest_sha256') IS DISTINCT FROM 'string'
     OR expected->>'manifest_sha256' !~ '^[0-9a-f]{64}$'
     OR expected->>'manifest_sha256' IS DISTINCT FROM operation.outer_manifest_sha256
     OR jsonb_typeof(expected->'components') IS DISTINCT FROM 'array'
     OR jsonb_typeof(expected->'entries') IS DISTINCT FROM 'array'
     OR jsonb_typeof(expected->'sequences') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'expected installation has invalid canonical schema or manifest binding';
  END IF;
  FOR component IN SELECT value FROM jsonb_array_elements(expected->'components') LOOP
    IF NOT public.backup_b1_exact_keys(component,
      ARRAY['component_id','makerspace_id','ciphertext_sha256'])
      OR jsonb_typeof(component->'component_id') IS DISTINCT FROM 'string'
      OR (component->>'component_id')::uuid::text IS DISTINCT FROM component->>'component_id'
      OR jsonb_typeof(component->'makerspace_id') IS DISTINCT FROM 'number'
      OR component->>'makerspace_id' !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(component->'ciphertext_sha256') IS DISTINCT FROM 'string'
      OR component->>'ciphertext_sha256' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'invalid expected component';
    END IF;
    PERFORM (component->>'makerspace_id')::bigint;
    key := component->>'component_id';
    IF key = ANY(identities) OR key COLLATE "C" <= previous_key COLLATE "C" THEN
      RAISE EXCEPTION 'duplicated or unsorted expected components';
    END IF;
    identities := array_append(identities, key);
    previous_key := key;
  END LOOP;
  IF cardinality(identities) = 0 THEN RAISE EXCEPTION 'empty expected components'; END IF;
  previous_key := '';
  FOR entry IN SELECT value FROM jsonb_array_elements(expected->'entries') LOOP
    IF NOT public.backup_b1_exact_keys(entry, ARRAY[
      'component_id','kind','registry_identity','definition_sha256','source_fact',
      'installed_payload','target_relation_oid','enforcement_function_oid'])
      OR jsonb_typeof(entry->'component_id') IS DISTINCT FROM 'string'
      OR NOT (entry->>'component_id' = ANY(identities))
      OR jsonb_typeof(entry->'kind') IS DISTINCT FROM 'string'
      OR entry->>'kind' NOT IN ('commitment','broad_fence','relationship_fence','object_namespace')
      OR jsonb_typeof(entry->'registry_identity') IS DISTINCT FROM 'string'
      OR entry->>'registry_identity' !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(entry->'definition_sha256') IS DISTINCT FROM 'string'
      OR entry->>'definition_sha256' !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(entry->'source_fact') IS DISTINCT FROM 'object'
      OR jsonb_typeof(entry->'installed_payload') IS DISTINCT FROM 'object'
      OR jsonb_typeof(entry->'target_relation_oid') IS DISTINCT FROM 'number'
      OR entry->>'target_relation_oid' !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(entry->'enforcement_function_oid') IS DISTINCT FROM 'number'
      OR entry->>'enforcement_function_oid' !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'invalid expected entry';
    END IF;
    key := concat_ws(':', entry->>'component_id', entry->>'kind', entry->>'registry_identity');
    IF key = ANY(entry_keys) OR key COLLATE "C" <= previous_key COLLATE "C" THEN
      RAISE EXCEPTION 'duplicated or unsorted expected entries';
    END IF;
    entry_keys := array_append(entry_keys, key);
    previous_key := key;
    fact := entry->'source_fact';
    payload := entry->'installed_payload';
    IF jsonb_typeof(fact->'definition_sha256') IS DISTINCT FROM 'string'
      OR jsonb_typeof(COALESCE(fact->'constraint_identity', fact->'registry_identity'))
        IS DISTINCT FROM 'string'
      OR fact->>'definition_sha256' IS DISTINCT FROM entry->>'definition_sha256'
      OR COALESCE(fact->>'constraint_identity', fact->>'registry_identity')
        IS DISTINCT FROM entry->>'registry_identity'
      OR NOT public.backup_b1_source_shape(entry, identities) THEN
      RAISE EXCEPTION 'invalid expected source fact';
    END IF;
    target_schema := COALESCE(payload->>'schema',payload->'enforcement'->>'schema','public');
    target_table := COALESCE(payload->>'table',payload->'enforcement'->>'table');
    IF to_regclass(format('%I.%I',target_schema,target_table))::oid
        IS DISTINCT FROM (entry->>'target_relation_oid')::oid
      OR to_regprocedure('public.backup_b1_enforce_reservations()')::oid
        IS DISTINCT FROM (entry->>'enforcement_function_oid')::oid THEN
      RAISE EXCEPTION 'expected target catalog identity changed';
    END IF;
    signature := jsonb_build_array(entry->'definition_sha256', payload,
      entry->'target_relation_oid', entry->'enforcement_function_oid');
    key := entry->>'registry_identity';
    IF shared ? key AND shared->key IS DISTINCT FROM signature THEN
      RAISE EXCEPTION 'conflicting shared reservation definitions';
    END IF;
    shared := shared || jsonb_build_object(key, signature);
  END LOOP;
  previous_key := '';
  FOR sequence_fact IN SELECT value FROM jsonb_array_elements(expected->'sequences') LOOP
    IF NOT public.backup_b1_sequence_shape(sequence_fact) THEN
      RAISE EXCEPTION 'invalid expected sequence';
    END IF;
    key := format('%I.%I', sequence_fact->>'schema', sequence_fact->>'sequence');
    IF key = ANY(sequence_keys) THEN
      RAISE EXCEPTION 'duplicated or unsorted expected sequences';
    END IF;
    sequence_keys := array_append(sequence_keys,key);
    previous_key := key;
  END LOOP;
  IF expected->'sequences' IS DISTINCT FROM (
    SELECT COALESCE(jsonb_agg(value ORDER BY value->>'schema' COLLATE "C",
      value->>'sequence' COLLATE "C"), '[]'::jsonb)
    FROM jsonb_array_elements(expected->'sequences')
  ) THEN RAISE EXCEPTION 'unsorted expected sequences'; END IF;
  RETURN expected;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""
