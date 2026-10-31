"""Frozen 0025 source/compiled fact shapes; executable additions are explicit."""

SQL = r"""
CREATE FUNCTION public.backup_b1_string_array(value jsonb) RETURNS boolean AS $$
BEGIN
  IF jsonb_typeof(value) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  RETURN NOT EXISTS (SELECT 1 FROM jsonb_array_elements(value) item
    WHERE jsonb_typeof(item) IS DISTINCT FROM 'string');
END;
$$ LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, public;

CREATE FUNCTION public.backup_b1_source_shape(entry jsonb, identities text[])
RETURNS boolean AS $$
DECLARE
  fact jsonb := entry->'source_fact';
  payload jsonb := entry->'installed_payload';
  enforcement jsonb;
  item jsonb;
  component jsonb;
  ids text[] := ARRAY[]::text[];
  names text[];
  key text;
  i integer;
BEGIN
  IF entry->>'kind' = 'commitment' THEN
    IF NOT public.backup_b1_exact_keys(fact, ARRAY[
      'constraint_identity','definition_sha256','canonicalizer_identity',
      'key_component_identities','component_commitments'])
      OR jsonb_typeof(fact->'canonicalizer_identity') IS DISTINCT FROM 'string'
      OR fact->>'canonicalizer_identity' !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(fact->'key_component_identities') IS DISTINCT FROM 'array'
      OR jsonb_typeof(fact->'component_commitments') IS DISTINCT FROM 'array'
      OR jsonb_array_length(fact->'key_component_identities') = 0 THEN RETURN false;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(fact->'component_commitments') LOOP
      IF NOT public.backup_b1_exact_keys(item, ARRAY['component_id','commitments'])
        OR jsonb_typeof(item->'component_id') IS DISTINCT FROM 'string'
        OR NOT (item->>'component_id' = ANY(identities))
        OR item->>'component_id' = ANY(ids)
        OR NOT public.backup_b1_string_array(item->'commitments') THEN RETURN false;
      END IF;
      ids := array_append(ids, item->>'component_id');
      IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(item->'commitments') value
          WHERE value !~ '^[0-9a-f]{64}$')
        OR item->'commitments' IS DISTINCT FROM (
          SELECT COALESCE(jsonb_agg(value ORDER BY value COLLATE "C"), '[]'::jsonb)
          FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(item->'commitments')) u
        ) THEN RETURN false;
      END IF;
    END LOOP;
    IF ARRAY(SELECT unnest(ids) ORDER BY 1) IS DISTINCT FROM identities THEN RETURN false; END IF;
    IF payload - 'enforcement' - 'reservation_salt' IS DISTINCT FROM fact
       OR NOT public.backup_b1_exact_keys(payload, ARRAY[
         'constraint_identity','definition_sha256','canonicalizer_identity',
         'key_component_identities','component_commitments','enforcement','reservation_salt'])
       OR jsonb_typeof(payload->'reservation_salt') IS DISTINCT FROM 'string'
       OR octet_length(decode(payload->>'reservation_salt','base64')) <> 32 THEN RETURN false;
    END IF;
    enforcement := payload->'enforcement';
    IF NOT public.backup_b1_exact_keys(enforcement,
      ARRAY['schema','table','predicate_sql','nulls_not_distinct','components'])
      OR jsonb_typeof(enforcement->'schema') IS DISTINCT FROM 'string'
      OR enforcement->>'schema' = ''
      OR jsonb_typeof(enforcement->'table') IS DISTINCT FROM 'string'
      OR enforcement->>'table' = ''
      OR jsonb_typeof(enforcement->'predicate_sql') IS DISTINCT FROM 'string'
      OR jsonb_typeof(enforcement->'nulls_not_distinct') IS DISTINCT FROM 'boolean'
      OR jsonb_typeof(enforcement->'components') IS DISTINCT FROM 'array'
      OR jsonb_array_length(enforcement->'components') <>
        jsonb_array_length(fact->'key_component_identities') THEN RETURN false;
    END IF;
    FOR i IN 0..jsonb_array_length(fact->'key_component_identities') - 1 LOOP
      item := fact->'key_component_identities'->i;
      component := enforcement->'components'->i;
      IF NOT public.backup_b1_exact_keys(item, ARRAY['type_identity','canonicalizer_identity'])
        OR jsonb_typeof(item->'type_identity') IS DISTINCT FROM 'string'
        OR item->>'type_identity' = ''
        OR jsonb_typeof(item->'canonicalizer_identity') IS DISTINCT FROM 'string'
        OR item->>'canonicalizer_identity' = ''
        OR NOT public.backup_b1_exact_keys(component,
          ARRAY['type_identity','canonicalizer_identity','canonicalizer_sql'])
        OR component - 'canonicalizer_sql' IS DISTINCT FROM item
        OR jsonb_typeof(component->'canonicalizer_sql') IS DISTINCT FROM 'string'
        OR component->>'canonicalizer_sql' = '' THEN RETURN false;
      END IF;
    END LOOP;
    RETURN true;
  END IF;
  names := ARRAY['version','definition_sha256','schema','table','columns',
    'operations','component_ids'];
  CASE entry->>'kind'
    WHEN 'broad_fence' THEN
      names := names || ARRAY['constraint_identity'];
      IF fact->>'version' IS DISTINCT FROM 'b1-broad-unique-fence-v1' THEN RETURN false; END IF;
    WHEN 'relationship_fence' THEN
      names := names || ARRAY['registry_identity','dependency_kind'];
      IF fact->>'version' IS DISTINCT FROM 'b1-relationship-fence-v1'
        OR jsonb_typeof(fact->'dependency_kind') IS DISTINCT FROM 'string'
        OR fact->>'dependency_kind' NOT IN (
          'boundary_inbound_fk','boundary_endpoint','semantic_reference') THEN RETURN false;
      END IF;
      IF fact->>'dependency_kind' = 'semantic_reference' THEN
        names := names || ARRAY['registered_variants'];
        IF NOT public.backup_b1_string_array(fact->'registered_variants') THEN RETURN false; END IF;
      END IF;
    WHEN 'object_namespace' THEN
      names := names || ARRAY['registry_identity','bucket_kind'];
      IF fact->>'version' IS DISTINCT FROM 'b1-object-namespace-fence-v1'
        OR jsonb_typeof(fact->'bucket_kind') IS DISTINCT FROM 'string'
        OR fact->>'bucket_kind' = '' THEN RETURN false;
      END IF;
    ELSE RETURN false;
  END CASE;
  IF NOT public.backup_b1_exact_keys(fact, names) OR payload IS DISTINCT FROM fact
    OR jsonb_typeof(fact->'schema') IS DISTINCT FROM 'string' OR fact->>'schema' = ''
    OR jsonb_typeof(fact->'table') IS DISTINCT FROM 'string' OR fact->>'table' = ''
    OR NOT public.backup_b1_string_array(fact->'columns')
    OR NOT public.backup_b1_string_array(fact->'component_ids')
    OR NOT public.backup_b1_string_array(fact->'operations') THEN RETURN false;
  END IF;
  IF jsonb_array_length(fact->'component_ids') = 0
    OR NOT (fact->'component_ids' ? (entry->>'component_id')) THEN RETURN false; END IF;
  FOR key IN SELECT jsonb_array_elements_text(fact->'component_ids') LOOP
    IF NOT (key = ANY(identities)) OR key = ANY(ids) THEN RETURN false; END IF;
    ids := array_append(ids,key);
  END LOOP;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(fact->'operations') op
    WHERE op NOT IN ('insert','update','delete','overwrite')
      OR (entry->>'kind' = 'broad_fence' AND op NOT IN ('insert','update'))) THEN RETURN false;
  END IF;
  RETURN true;
END;
$$ LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, public;
"""
