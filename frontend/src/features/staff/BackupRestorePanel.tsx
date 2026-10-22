import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, Field, Input, SettingsRow, Switch, useToast } from "../../components/ui";
import { BackupArchiveTable, formatDate } from "./BackupArchiveTable";
import { BackupRestoreDecision } from "./BackupRestoreDecision";
import {
  decideRestore,
  getBackupSettings,
  getRestore,
  issueBackupDownload,
  listDeploymentBackups,
  listRestores,
  listTenantBackups,
  requestDeploymentBackup,
  requestRestore,
  requestTenantBackup,
  updateBackupSettings,
  type BackupArchive,
} from "./backupApi";
import { errorText, Panel } from "./panels/shared";

export function BackupRestorePanel({ makerspaceId, isSuperadmin, singleTenantLocked = false }: {
  makerspaceId: number;
  isSuperadmin: boolean;
  /** An origin-locked deployment refuses the /admin/platform/ backup and restore routes. */
  singleTenantLocked?: boolean;
}) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const platform = isSuperadmin && !singleTenantLocked;
  const tenantKey = ["tenant-backups", makerspaceId];
  const deploymentKey = ["deployment-backups"];
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });
  const tenant = useQuery({ queryKey: tenantKey, queryFn: () => listTenantBackups(makerspaceId), refetchInterval: pollArchives });
  const deployment = useQuery({ queryKey: deploymentKey, queryFn: listDeploymentBackups, enabled: platform, refetchInterval: pollArchives });
  const settings = useQuery({ queryKey: ["backup-settings"], queryFn: getBackupSettings, enabled: platform });
  const restores = useQuery({ queryKey: ["restore-operations"], queryFn: listRestores, enabled: platform, refetchInterval: 3000 });
  const activeRestore = restores.data?.find((row) => !["completed", "failed", "aborted", "restored_quarantined"].includes(row.stage));
  const restoreDetail = useQuery({ queryKey: ["restore-operation", activeRestore?.id], queryFn: () => getRestore(activeRestore!.id), enabled: platform && Boolean(activeRestore), refetchInterval: 1000 });
  const createTenant = useMutation({
    mutationFn: () => requestTenantBackup(makerspaceId),
    onSuccess: () => { client.invalidateQueries({ queryKey: tenantKey }); showToast("Archive requested", { tone: "success" }); },
    onError: failed("Couldn't request the archive"),
  });
  const createDeployment = useMutation({
    mutationFn: requestDeploymentBackup,
    onSuccess: () => { client.invalidateQueries({ queryKey: deploymentKey }); showToast("Deployment archive requested", { tone: "success" }); },
    onError: failed("Couldn't request the deployment archive"),
  });
  const saveSettings = useMutation({
    mutationFn: updateBackupSettings,
    onSuccess: (data) => { client.setQueryData(["backup-settings"], data); showToast("Backup settings saved", { tone: "success" }); },
    onError: failed("Couldn't save the backup settings"),
  });
  const download = useMutation({
    mutationFn: issueBackupDownload,
    onSuccess: ({ url }) => { showToast("Download starting", { tone: "info" }); window.location.assign(url); },
    onError: failed("Couldn't prepare the download"),
  });
  const startRestore = useMutation({
    mutationFn: ({ archive, kind }: { archive: string; kind: "rollback_in_place" | "disaster" }) => requestRestore(archive, kind),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["restore-operations"] }); showToast("Restore started", { tone: "success" }); },
    onError: failed("Couldn't start the restore"),
  });
  const decision = useMutation({
    mutationFn: ({ id, value }: { id: string; value: "proceed" | "reset" | "abort" }) => decideRestore(id, value),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["restore-operations"] }); showToast("Decision recorded", { tone: "success" }); },
    onError: failed("Couldn't record the decision"),
  });
  const anyError = tenant.error || deployment.error || settings.error || restores.error || createTenant.error || createDeployment.error
    || saveSettings.error || download.error || startRestore.error || decision.error;

  return (
    <Panel
      title="Backup & restore"
      description="Encrypted archives of this makerspace, and of the whole deployment for superadmins."
      actions={<Button variant="primary" loading={createTenant.isPending} loadingLabel="Requesting…" onClick={() => createTenant.mutate()}>Create makerspace archive</Button>}
    >
      <div className="grid gap-6">
        {anyError ? <Callout tone="danger" role="alert">A backup operation failed. Refresh for the persisted status.</Callout> : null}
        <Card as="section">
          <CardHeader title="Makerspace backups" description="Archives of this makerspace's data only." />
          <div className="grid gap-4">
            <ArchiveDisclosure deployment={false} />
            <BackupArchiveTable label="Makerspace archives" rows={tenant.data ?? []} loading={tenant.isLoading} downloadPending={download.isPending} onDownload={(id) => download.mutate(id)} />
          </div>
        </Card>
        {platform ? (
          <Card as="section" aria-label="Deployment backup and restore">
            <CardHeader
              title="Deployment backup and restore"
              description="Full archives of every makerspace and the platform itself."
              action={<Button variant="secondary" loading={createDeployment.isPending} loadingLabel="Requesting…" onClick={() => createDeployment.mutate()}>Create full deployment archive</Button>}
            />
            <ArchiveDisclosure deployment />
            <SettingsRow title="Daily archive" description={`Last successful archive: ${formatDate(settings.data?.last_success_at)}`}>
              <div className="flex items-center justify-between gap-4">
                <label htmlFor="automatic-backups" className="text-body-ui text-ink">Create a full deployment archive each day</label>
                <Switch
                  id="automatic-backups"
                  checked={settings.data?.automatic_backups_enabled ?? false}
                  disabled={saveSettings.isPending || settings.isLoading}
                  onCheckedChange={(checked) => saveSettings.mutate({ automatic_backups_enabled: checked })}
                />
              </div>
              {settings.data?.last_error ? <p className="mt-2 text-caption text-danger-fg" role="alert">{settings.data.last_error}</p> : null}
            </SettingsRow>
            <SettingsRow title="Retention" description="Archives older than this are deleted. Saved when you leave the field.">
              <Field label="Archive retention (days)" className="max-w-xs">
                <Input
                  type="number"
                  min={1}
                  max={3650}
                  key={settings.data?.retention_days}
                  defaultValue={settings.data?.retention_days ?? 30}
                  onBlur={(event) => saveSettings.mutate({ retention_days: Math.max(1, Number(event.target.value) || 30) })}
                />
              </Field>
            </SettingsRow>
            <div className="grid gap-4 border-t border-line pt-6">
              <BackupArchiveTable
                label="Deployment archives"
                rows={deployment.data ?? []}
                loading={deployment.isLoading}
                downloadPending={download.isPending}
                onDownload={(id) => download.mutate(id)}
                restorePending={startRestore.isPending}
                onRestore={(archive, kind) => startRestore.mutateAsync({ archive, kind }).catch(() => undefined)}
              />
              {restoreDetail.data ? (
                <BackupRestoreDecision
                  operation={restoreDetail.data}
                  pending={decision.isPending}
                  onDecide={(value) => decision.mutateAsync({ id: restoreDetail.data!.id, value }).catch(() => undefined)}
                />
              ) : null}
            </div>
          </Card>
        ) : null}
      </div>
    </Panel>
  );
}

function ArchiveDisclosure({ deployment }: { deployment: boolean }) {
  return (
    <Callout tone="warning">
      This {deployment ? "deployment archive contains production data and continuity secrets" : "makerspace archive contains production tenant data"}, encrypted to the configured age recipient. Downloaded copies are outside makerspace purge guarantees; delete retained copies separately.
    </Callout>
  );
}

function pollArchives(query: { state: { data?: BackupArchive[] } }) {
  return query.state.data?.some((row) => row.status === "pending" || row.status === "running" || row.status === "promoting") ? 2000 : false;
}
