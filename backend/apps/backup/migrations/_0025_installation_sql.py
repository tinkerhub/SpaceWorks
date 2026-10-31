"""Frozen 0025 complete inventory, live enforcement and continuity proof."""

SQL = r"""
CREATE FUNCTION public.backup_b1_live_guard(target oid, enforcement oid) RETURNS oid AS $$
  SELECT t.oid FROM pg_catalog.pg_trigger t
   WHERE t.tgrelid=target AND t.tgname='backup_b1_reservation_guard'
     AND t.tgfoid=enforcement
     AND enforcement=to_regprocedure('public.backup_b1_enforce_reservations()')::oid
     AND t.tgtype=31 AND t.tgenabled IN ('O','A')
     AND NOT t.tgisinternal AND NOT t.tgdeferrable AND NOT t.tginitdeferred
     AND t.tgconstraint=0 AND t.tgconstrrelid=0 AND t.tgconstrindid=0
     AND t.tgnargs=0 AND octet_length(t.tgargs)=0
     AND t.tgattr=''::int2vector AND t.tgqual IS NULL
     AND t.tgoldtable IS NULL AND t.tgnewtable IS NULL;
-- VOLATILE sees a guard just created inside the current reservation INSERT trigger.
$$ LANGUAGE sql VOLATILE SET search_path = pg_catalog, public;

CREATE FUNCTION public.backup_b1_prove_installation(
  operation public.backup_b1restoreoperationstate, verified boolean, stamps boolean DEFAULT true
) RETURNS boolean AS $$
DECLARE
  expected jsonb := public.backup_b1_expected_inventory(operation);
  fact jsonb;
  component public.backup_b1restorecomponentstate%ROWTYPE;
  entry public.backup_b1reservationentry%ROWTYPE;
  continuity public.backup_b1fencecontinuity%ROWTYPE;
  trigger_oid oid;
  required_fences jsonb := '{}'::jsonb;
  fence_identity text;
  expected_fence jsonb;
BEGIN
  IF (SELECT count(*) FROM public.backup_b1restorecomponentstate
    WHERE operation_id=operation.operation_id) <> jsonb_array_length(expected->'components')
    OR (SELECT count(*) FROM public.backup_b1reservationentry
    WHERE operation_id=operation.operation_id) <> jsonb_array_length(expected->'entries') THEN
    RAISE EXCEPTION 'incomplete or extra pre-cutover installation inventory';
  END IF;
  FOR fact IN SELECT value FROM jsonb_array_elements(expected->'components') LOOP
    SELECT * INTO component FROM public.backup_b1restorecomponentstate
      WHERE operation_id=operation.operation_id AND component_id=(fact->>'component_id')::uuid;
    IF NOT FOUND THEN RAISE EXCEPTION 'expected component is missing'; END IF;
    IF component.artifact_id <> operation.artifact_id OR component.capture_id <> operation.capture_id
      OR component.makerspace_id_snapshot <> (fact->>'makerspace_id')::bigint
      OR component.ciphertext_sha256 IS DISTINCT FROM fact->>'ciphertext_sha256'
      OR component.state <> 'pending' OR component.merge_checkpoint <> ''
      OR component.dependency_facts <> '[]'::jsonb THEN
      RAISE EXCEPTION 'expected component identity or pre-cutover state changed';
    END IF;
  END LOOP;
  FOR fact IN SELECT value FROM jsonb_array_elements(expected->'entries') LOOP
    SELECT * INTO entry FROM public.backup_b1reservationentry
      WHERE operation_id=operation.operation_id AND component_id=(fact->>'component_id')::uuid
        AND kind=fact->>'kind' AND registry_identity=fact->>'registry_identity';
    IF NOT FOUND THEN RAISE EXCEPTION 'expected reservation is missing'; END IF;
    IF entry.definition_sha256 IS DISTINCT FROM fact->>'definition_sha256'
      OR entry.safe_payload IS DISTINCT FROM fact->'installed_payload'
      OR entry.installed_at IS NULL OR (verified AND stamps AND entry.catalog_verified_at IS NULL) THEN
      RAISE EXCEPTION 'installed reservation does not equal the immutable compiled payload';
    END IF;
    trigger_oid := public.backup_b1_live_guard((fact->>'target_relation_oid')::oid,
      (fact->>'enforcement_function_oid')::oid);
    IF trigger_oid IS NULL THEN RAISE EXCEPTION 'live reservation trigger is missing or unsafe'; END IF;
    IF fact->>'kind' IN ('broad_fence','relationship_fence','object_namespace') THEN
      fence_identity := fact->>'registry_identity';
      -- Match Python integer continuity OIDs; oid otherwise becomes a JSON string.
      expected_fence := jsonb_build_array(fact->>'definition_sha256', trigger_oid::bigint);
      IF required_fences ? fence_identity AND required_fences->fence_identity <> expected_fence THEN
        RAISE EXCEPTION 'conflicting shared continuity definition';
      END IF;
      required_fences := required_fences || jsonb_build_object(fence_identity,expected_fence);
    END IF;
  END LOOP;
  IF verified THEN
    IF (SELECT count(*) FROM public.backup_b1fencecontinuity
      WHERE operation_id=operation.operation_id) <>
        (SELECT count(*) FROM jsonb_object_keys(required_fences)) THEN
      RAISE EXCEPTION 'incomplete or unrelated continuity inventory';
    END IF;
    FOR fence_identity, expected_fence IN SELECT * FROM jsonb_each(required_fences) LOOP
      SELECT * INTO continuity FROM public.backup_b1fencecontinuity
        WHERE operation_id=operation.operation_id AND registry_identity=fence_identity;
      IF NOT FOUND THEN RAISE EXCEPTION 'required fence continuity is missing'; END IF;
      IF continuity.enabled IS NOT TRUE
        OR continuity.definition_sha256 IS DISTINCT FROM expected_fence->>0
        OR continuity.trigger_oids IS DISTINCT FROM jsonb_build_array(expected_fence->1) THEN
        RAISE EXCEPTION 'required enabled fence continuity OID or definition changed';
      END IF;
    END LOOP;
  END IF;
  IF NOT public.backup_b1_prove_sequences(expected->'sequences') THEN
    RAISE EXCEPTION 'signed sequence catalog or actual collision-safe frontier changed';
  END IF;
  RETURN true;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""
