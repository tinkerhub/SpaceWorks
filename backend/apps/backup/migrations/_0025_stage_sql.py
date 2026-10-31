"""Frozen operation-stage guard, preserving original identity/rank/failure paths."""

SQL = r"""
CREATE OR REPLACE FUNCTION public.backup_b1_restore_operation_guard() RETURNS trigger AS $$
DECLARE
  old_rank integer;
  new_rank integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'compound restore operation state cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.stage <> 'verified' THEN
      RAISE EXCEPTION 'compound restore operation must begin at verified';
    END IF;
    PERFORM public.backup_b1_expected_inventory(NEW);
    RETURN NEW;
  END IF;
  IF OLD.expected_installation IS DISTINCT FROM NEW.expected_installation
     OR OLD.expected_installation_sha256 IS DISTINCT FROM NEW.expected_installation_sha256 THEN
    RAISE EXCEPTION 'expected installation text and digest are immutable from INSERT';
  END IF;
  IF OLD.operation_id <> NEW.operation_id
     OR OLD.artifact_id <> NEW.artifact_id
     OR OLD.capture_id <> NEW.capture_id
     OR OLD.main_component_id <> NEW.main_component_id
     OR OLD.outer_ciphertext_sha256 <> NEW.outer_ciphertext_sha256
     OR OLD.outer_manifest_sha256 <> NEW.outer_manifest_sha256
     OR OLD.source_proof_sha256 <> NEW.source_proof_sha256
     OR OLD.sibling_database_name <> NEW.sibling_database_name
     OR OLD.sibling_database_oid <> NEW.sibling_database_oid
     OR OLD.sibling_server_identity <> NEW.sibling_server_identity
     OR OLD.created_at <> NEW.created_at THEN
    RAISE EXCEPTION 'compound restore operation identity is immutable';
  END IF;
  IF OLD.fence_continuity_digest <> ''
     AND OLD.fence_continuity_digest <> NEW.fence_continuity_digest
     OR OLD.object_journal_evidence_sha256 <> ''
     AND OLD.object_journal_evidence_sha256 <> NEW.object_journal_evidence_sha256
     OR OLD.quarantine_evidence_sha256 <> ''
     AND OLD.quarantine_evidence_sha256 <> NEW.quarantine_evidence_sha256
     OR OLD.cutover_attestation <> '{}'::jsonb
     AND OLD.cutover_attestation <> NEW.cutover_attestation
     OR OLD.failure_code <> '' AND OLD.failure_code <> NEW.failure_code THEN
    RAISE EXCEPTION 'compound restore evidence is immutable once recorded';
  END IF;
  IF OLD.stage = NEW.stage THEN
    RETURN NEW;
  END IF;
  IF OLD.stage = 'failed' OR NEW.stage = 'verified' THEN
    RAISE EXCEPTION 'compound restore stage cannot move backwards';
  END IF;
  IF NEW.stage = 'failed' THEN
    IF NEW.failure_code = '' THEN
      RAISE EXCEPTION 'failed compound restore stage requires a failure code';
    END IF;
    RETURN NEW;
  END IF;
  old_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], OLD.stage);
  new_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], NEW.stage);
  IF old_rank IS NULL OR new_rank IS NULL OR new_rank <> old_rank + 1 THEN
    RAISE EXCEPTION 'compound restore stages must advance exactly one step';
  END IF;
  -- Same-stage and failure paths above deliberately remain available to legacy history.
  PERFORM public.backup_b1_expected_inventory(NEW);
  IF new_rank >= 5 THEN
    PERFORM public.backup_b1_prove_installation(NEW, new_rank >= 6);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""

REVERSE = r"""
CREATE OR REPLACE FUNCTION public.backup_b1_restore_operation_guard() RETURNS trigger AS $$
DECLARE
  old_rank integer;
  new_rank integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'compound restore operation state cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.stage <> 'verified' THEN
      RAISE EXCEPTION 'compound restore operation must begin at verified';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.operation_id <> NEW.operation_id
     OR OLD.artifact_id <> NEW.artifact_id
     OR OLD.capture_id <> NEW.capture_id
     OR OLD.main_component_id <> NEW.main_component_id
     OR OLD.outer_ciphertext_sha256 <> NEW.outer_ciphertext_sha256
     OR OLD.outer_manifest_sha256 <> NEW.outer_manifest_sha256
     OR OLD.source_proof_sha256 <> NEW.source_proof_sha256
     OR OLD.sibling_database_name <> NEW.sibling_database_name
     OR OLD.sibling_database_oid <> NEW.sibling_database_oid
     OR OLD.sibling_server_identity <> NEW.sibling_server_identity
     OR OLD.created_at <> NEW.created_at THEN
    RAISE EXCEPTION 'compound restore operation identity is immutable';
  END IF;
  IF OLD.fence_continuity_digest <> ''
     AND OLD.fence_continuity_digest <> NEW.fence_continuity_digest
     OR OLD.object_journal_evidence_sha256 <> ''
     AND OLD.object_journal_evidence_sha256 <> NEW.object_journal_evidence_sha256
     OR OLD.quarantine_evidence_sha256 <> ''
     AND OLD.quarantine_evidence_sha256 <> NEW.quarantine_evidence_sha256
     OR OLD.cutover_attestation <> '{}'::jsonb
     AND OLD.cutover_attestation <> NEW.cutover_attestation
     OR OLD.failure_code <> '' AND OLD.failure_code <> NEW.failure_code THEN
    RAISE EXCEPTION 'compound restore evidence is immutable once recorded';
  END IF;
  IF OLD.stage = NEW.stage THEN
    RETURN NEW;
  END IF;
  IF OLD.stage = 'failed' OR NEW.stage = 'verified' THEN
    RAISE EXCEPTION 'compound restore stage cannot move backwards';
  END IF;
  IF NEW.stage = 'failed' THEN
    IF NEW.failure_code = '' THEN
      RAISE EXCEPTION 'failed compound restore stage requires a failure code';
    END IF;
    RETURN NEW;
  END IF;
  old_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], OLD.stage);
  new_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], NEW.stage);
  IF old_rank IS NULL OR new_rank <> old_rank + 1 THEN
    RAISE EXCEPTION 'compound restore stages must advance exactly one step';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
