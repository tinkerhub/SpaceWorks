import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Callout, Card, CardHeader, Chip, ConfirmDialog, Skeleton, StatusChip, Switch, useToast } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { cn } from "../../lib/cn";
import { Panel, useStaffGet } from "./panels/shared";

type ModuleRow = {
  key: string;
  label: string;
  description: string;
  installed: boolean;
  core: boolean;
  available: boolean;
  requires: string[];
  pulls_in: string[];
  required_by: string[];
  workflows: string[];
};

type ModuleGroup = {
  key: string;
  label: string;
  description: string;
  always_on: boolean;
  installed_count: number;
  module_count: number;
  modules: ModuleRow[];
};

type DeploymentApp = { app_label: string; shipped: boolean; note: string };

type ModulesResponse = {
  groups: ModuleGroup[];
  deployment: { apps: DeploymentApp[]; env_line: string; requires_restart: boolean };
};

type Change = { key: string; label: string; action: "install" | "uninstall" };

const errorText = (error: unknown) =>
  error instanceof StructuredApiError ? error.detail ?? error.message : "Unable to change modules.";

const DESCRIPTION = "Switch features on for this makerspace. Uninstalling keeps every row, upload and record; reinstalling restores them.";

export function ModulesPanel({ makerspaceId, makerspaceSlug }: { makerspaceId: number; makerspaceSlug: string }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const queryKey = ["modules", makerspaceId];
  const modules = useStaffGet<ModulesResponse>(queryKey, `/admin/makerspace/${makerspaceId}/modules`);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<Change | null>(null);

  const change = useMutation({
    mutationFn: ({ key, action }: Change) =>
      staffRequest(`/admin/makerspace/${makerspaceId}/modules/${action}`, {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
    // The server returns the recomputed groups, but invalidating is what keeps the rest
    // of the console honest: enabled_modules drives every tab gate, so a stale
    // makerspaces query would leave tabs visible for a module just uninstalled. The settings
    // row and every tenant bootstrap (runtime token, origin, `/m/:slug`, member area) carry
    // the module list too, and the runtime ones never go stale on their own.
    onSuccess: (_data, { label, action }) => {
      client.invalidateQueries({ queryKey });
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      client.invalidateQueries({ queryKey: ["makerspace-settings", makerspaceId] });
      client.invalidateQueries({ queryKey: ["runtime-tenant"] });
      client.invalidateQueries({ queryKey: ["runtime-tenant-origin"] });
      client.invalidateQueries({ queryKey: ["tenant-bootstrap", makerspaceSlug] });
      client.invalidateQueries({ queryKey: ["member", makerspaceSlug, "bootstrap"] });
      client.invalidateQueries({ queryKey: ["report-catalog"] });
      client.invalidateQueries({ queryKey: ["operations-report"] });
      // Role capabilities and notification rules are listed per installed module.
      client.invalidateQueries({ queryKey: ["staff", "capabilities", makerspaceId] });
      client.invalidateQueries({ queryKey: ["notification-rules", makerspaceId] });
      setPendingUninstall(null);
      showToast(action === "install" ? `${label} installed` : `${label} uninstalled`, { tone: "success" });
    },
    onError: (error) => showToast(errorText(error), { tone: "error" }),
  });

  if (modules.isLoading) {
    return (
      <Panel title="Modules" description={DESCRIPTION}>
        <div className="grid gap-3" aria-busy="true">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </Panel>
    );
  }
  if (modules.isError) {
    return (
      <Panel title="Modules" description={DESCRIPTION}>
        <Callout tone="danger" role="alert" title="Modules couldn't load">{errorText(modules.error)}</Callout>
      </Panel>
    );
  }

  const groups = modules.data?.groups ?? [];
  const deployment = modules.data?.deployment;

  return (
    <Panel title="Modules" description={DESCRIPTION}>
      <div className="grid gap-6">
        <p className="text-body-ui text-ink-muted">Deleting a module's data is a separate step run from the command line.</p>
        {change.isError ? <Callout tone="danger" role="alert">{errorText(change.error)}</Callout> : null}
        <div className="grid gap-3">
          {groups.map((group) => {
            const open = openGroup === group.key;
            return (
              <Card key={group.key} as="section" padding="none">
                <button
                  type="button"
                  aria-expanded={open}
                  className="flex w-full flex-wrap items-center justify-between gap-3 rounded-lg p-4 text-left transition-colors hover:bg-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus sm:p-5"
                  onClick={() => setOpenGroup(open ? null : group.key)}
                >
                  <span className="min-w-0">
                    <span className="block text-title text-ink">{group.label}</span>
                    <span className="block text-body-ui text-ink-muted">{group.description}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {group.always_on ? (
                      <Chip tone="neutral" size="sm">Always on</Chip>
                    ) : (
                      <StatusChip tone={group.installed_count ? "success" : "neutral"} size="sm">
                        {`${group.installed_count} of ${group.module_count} installed`}
                      </StatusChip>
                    )}
                    <ChevronDown aria-hidden="true" className={cn("size-5 text-ink-muted transition-transform duration-180", open && "rotate-180")} />
                  </span>
                </button>
                {/* Unmounted rather than hidden: a keyboard user must not be able to tab
                    into an Install switch they cannot see. */}
                {open ? (
                  <div className="border-t border-line px-4 sm:px-5">
                    {group.modules.map((module) => (
                      <ModuleRowItem
                        key={module.key}
                        module={module}
                        pending={change.isPending}
                        onInstall={() => change.mutate({ key: module.key, label: module.label, action: "install" })}
                        onUninstall={() => setPendingUninstall({ key: module.key, label: module.label, action: "uninstall" })}
                      />
                    ))}
                  </div>
                ) : null}
              </Card>
            );
          })}
        </div>

        {deployment ? (
          <Card as="section">
            <CardHeader
              title="Deployment"
              description="These apps can be removed from the build entirely, which drops their routes, admin screens and API schema for every makerspace. It is read from the environment at start-up, so this is a copyable line rather than a switch: the running process cannot change it without a restart."
            />
            <ul className="grid">
              {deployment.apps.map((app) => (
                <li key={app.app_label} className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-3">
                  <span className="min-w-0">
                    <span className="font-mono text-sm text-ink">{app.app_label}</span>
                    {app.note ? <span className="block text-caption text-ink-muted">{app.note}</span> : null}
                  </span>
                  <StatusChip tone={app.shipped ? "success" : "neutral"} size="sm">{app.shipped ? "Shipped" : "Removed"}</StatusChip>
                </li>
              ))}
            </ul>
            <pre className="mt-3 overflow-x-auto rounded-md border border-line bg-subtle p-3 font-mono text-xs text-ink">{deployment.env_line}</pre>
          </Card>
        ) : null}
      </div>
      <ConfirmDialog
        open={pendingUninstall !== null}
        title={pendingUninstall ? `Uninstall ${pendingUninstall.label}?` : "Uninstall module?"}
        message="Its tabs, settings and endpoints switch off for this makerspace. Rows, uploads and history are kept, and reinstalling restores everything."
        confirmLabel="Uninstall"
        tone="danger"
        pending={change.isPending}
        onConfirm={() => { if (pendingUninstall) change.mutate(pendingUninstall); }}
        onCancel={() => setPendingUninstall(null)}
      />
    </Panel>
  );
}

function ModuleRowItem({ module, pending, onInstall, onUninstall }: {
  module: ModuleRow;
  pending: boolean;
  onInstall: () => void;
  onUninstall: () => void;
}) {
  const blocked = module.required_by.length > 0;
  const switchId = `module-${module.key}`;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-t border-line py-4 first:border-t-0">
      <div className="min-w-0 flex-1">
        <label htmlFor={module.core ? undefined : switchId} className="text-label text-ink">{module.label}</label>
        <p className="text-body-ui text-ink-muted">{module.description}</p>
        {module.workflows.length ? (
          <p className="mt-1 text-caption text-ink-muted">Turns on: {module.workflows.join(", ")}</p>
        ) : null}
        {/* Shown before the switch: a dependency resolved silently is a capability the
            operator did not choose. */}
        {!module.installed && module.pulls_in.length ? (
          <p className="mt-1 text-caption text-ink-muted">Also installs: {module.pulls_in.join(", ")}</p>
        ) : null}
        {blocked ? <p className="mt-1 text-caption text-ink-muted">Required by {module.required_by.join(", ")}</p> : null}
        {!module.available ? <p className="mt-1 text-caption text-ink-muted">Not shipped by this deployment.</p> : null}
      </div>
      <div className="flex items-center gap-3">
        {module.core ? (
          <Chip tone="neutral" size="sm">Core</Chip>
        ) : (
          <>
            <StatusChip tone={module.installed ? "success" : "neutral"} size="sm">{module.installed ? "Installed" : "Off"}</StatusChip>
            <Switch
              id={switchId}
              checked={module.installed}
              disabled={pending || (module.installed ? blocked : !module.available)}
              onCheckedChange={(checked) => (checked ? onInstall() : onUninstall())}
            />
          </>
        )}
      </div>
    </div>
  );
}
