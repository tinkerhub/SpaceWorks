import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, EmptyState, Field, Input, Skeleton, useToast } from "../../components/ui";
import { TenantMigrationImportCard } from "./TenantMigrationImportCard";
import { createImport, listImports, tenantMigrationKeys, type Pairing } from "./tenantMigrationApi";
import { ErrorText, migrationError } from "./tenantMigrationUi";

export function TenantMigrationImports({ pairings }: { pairings: Pairing[] }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [archive, setArchive] = useState<File | null>(null);
  const [digest, setDigest] = useState("");
  const imports = useQuery({
    queryKey: tenantMigrationKeys.imports,
    queryFn: listImports,
  });
  const create = useMutation({
    mutationFn: () => createImport({ archive: archive!, source_archive_digest: digest.trim() }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
      showToast("Target import created", { tone: "success" });
    },
    onError: (error) => showToast(migrationError(error, "source_archive_digest"), { tone: "error" }),
  });
  const jobs = imports.data ?? [];

  return (
    <Card as="section" aria-labelledby="migration-import-title">
      <CardHeader
        title={<span id="migration-import-title">Import and verify target</span>}
        description="Target deployment. Materialization creates an importing tenant; it isn't live until you activate it."
      />
      <p className="text-body-ui text-ink-secondary">
        Upload the age-encrypted archive and bind it to the digest shown on the source export.
      </p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <Field label="Encrypted archive">
          <Input type="file" onChange={(event) => setArchive(event.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Source archive digest">
          <Input className="font-mono" value={digest} onChange={(event) => setDigest(event.target.value)} />
        </Field>
      </div>
      <Button
        className="mt-4"
        variant="primary"
        disabled={!archive || !digest.trim()}
        loading={create.isPending}
        loadingLabel="Uploading encrypted archive…"
        onClick={() => create.mutate()}
      >
        Create target import
      </Button>
      <ErrorText error={create.error} field="source_archive_digest" />
      <div className="mt-6 grid gap-4">
        {imports.isLoading ? <Skeleton className="h-24 w-full" /> : null}
        <ErrorText error={imports.error} />
        {!imports.isLoading && !imports.error && jobs.length === 0 ? (
          <EmptyState title="No target imports yet" description="Upload an encrypted archive from the source deployment to start one." />
        ) : null}
        {jobs.map((job) => (
          <TenantMigrationImportCard job={job} key={job.id} pairing={pairings.find((item) => item.migration_id === job.id)} />
        ))}
      </div>
    </Card>
  );
}
