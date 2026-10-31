import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/ui";
import { BackupArchiveTable } from "./BackupArchiveTable";
import { BackupRestorePanel } from "./BackupRestorePanel";
import type { BackupArchive } from "./backupApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
vi.mock("../../components/SpaceWorksLogo", () => ({ SpaceWorksBadge: () => <span>SpaceWorks</span> }));

const archiveId = "12345678-1234-4234-8234-123456789abc";
const restoreId = "87654321-1234-4234-8234-123456789abc";
function archive(manifest: BackupArchive["manifest"]): BackupArchive {
  return { id: archiveId, scope: "deployment", makerspace: null, status: "available", manifest,
    size_bytes: 100, age_encrypted: true, failure_detail: "", expires_at: "2027-01-01T00:00:00Z",
    created_at: "2026-10-29T00:00:00Z", purge_warning: "Downloaded copies remain." };
}

beforeEach(() => { staffRequest.mockReset(); });

describe("backup archive restore availability", () => {
  it.each([
    ["signed full", { format: "spaceworks-deployment-full-v1" }, "Signed full deployment"],
    ["legacy v1", { format: "spaceworks-phase5a-v1" }, "Historical full deployment"],
    ["legacy v2", { format: "spaceworks-phase5a-v2" }, "Historical full deployment"],
    ["legacy v3", { format: "spaceworks-phase5a-v3", partial: false }, "Historical full deployment"],
  ] satisfies Array<[string, BackupArchive["manifest"], string]>)("offers restore for %s", (_name, manifest, label) => {
    const onDownload = vi.fn();
    render(<BackupArchiveTable label="Archives" rows={[archive(manifest)]} loading={false}
      downloadPending={false} onDownload={onDownload} onRestore={vi.fn().mockResolvedValue({})} />);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByRole("button", { name: "Rollback here…" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disaster restore…" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(onDownload).toHaveBeenCalledWith(archiveId);
  });

  it.each([
    ["B1 partial", { format: "spaceworks-phase5a-v3", protocol_version: "spaceworks-lane-e-b1-v2", partial: true }],
    ["B1 full-looking", { format: "spaceworks-phase5a-v3", protocol_version: "spaceworks-lane-e-b1-v2", partial: false }],
    ["old B1", { format: "spaceworks-lane-e-e3-compound-v1", partial: false }],
    ["future", { format: "future-format", partial: false }],
    ["signed legacy header", { format: "spaceworks-phase5a-v3", archive_signature: {} }],
    ["unidentified", {}],
  ] satisfies Array<[string, BackupArchive["manifest"]]>)("retains download but no restore for %s", (_name, manifest) => {
    const onDownload = vi.fn();
    render(<BackupArchiveTable label="Archives" rows={[archive(manifest)]} loading={false}
      downloadPending={false} onDownload={onDownload} onRestore={vi.fn().mockResolvedValue({})} />);
    expect(screen.queryByRole("button", { name: /rollback|disaster restore/i })).not.toBeInTheDocument();
    expect(screen.getByText(/restore unavailable/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(onDownload).toHaveBeenCalledWith(archiveId);
  });

  it.each(["disaster", "rollback_in_place"] as const)("explains %s before recording intent", async (kind) => {
    const onRestore = vi.fn().mockResolvedValue({});
    render(<BackupArchiveTable label="Archives" rows={[archive({ format: "spaceworks-deployment-full-v1" })]}
      loading={false} downloadPending={false} onDownload={vi.fn()} onRestore={onRestore} />);
    fireEvent.click(screen.getByRole("button", { name: kind === "disaster" ? "Disaster restore…" : "Rollback here…" }));
    const dialog = screen.getByRole("alertdialog");
    if (kind === "disaster") {
      expect(within(dialog).getByText(/replaces deployment data.*resets authority/i)).toBeVisible();
      expect(within(dialog).queryByText(/all-table report/i)).not.toBeInTheDocument();
      expect(within(dialog).getByText(/privileged host operator/i)).toBeVisible();
    } else {
      expect(within(dialog).getByText(/all-table report.*decide/i)).toBeVisible();
    }
    fireEvent.click(within(dialog).getByRole("button", { name: kind === "disaster"
      ? "Record disaster restore intent" : "Record rollback intent" }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledWith(archiveId, kind));
  });
});

describe("restore intent handoff", () => {
  it.each([restoreId, "unsafe; do-not-execute"])("shows privileged supervisor instruction safely for %s", async (id) => {
    const operation = { id, archive: archiveId, kind: "disaster", stage: "requested", decision: "pending",
      restore_diff: {}, decision_deadline_at: null, error_detail: "", requested_at: "2026-10-29T00:00:00Z" };
    let recorded = false;
    staffRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/admin/platform/backups") return Promise.resolve([archive({ format: "spaceworks-deployment-full-v1" })]);
      if (path === "/admin/platform/backup-settings") return Promise.resolve({ automatic_backups_enabled: false,
        retention_days: 30, last_scheduled_at: null, last_success_at: null, last_error: "" });
      if (path === "/admin/platform/restores" && options?.method === "POST") {
        recorded = true;
        return Promise.resolve(operation);
      }
      if (path === "/admin/platform/restores") return Promise.resolve(recorded ? [operation] : []);
      if (path.startsWith("/admin/platform/restores/")) return Promise.resolve(operation);
      return Promise.resolve([]);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ToastProvider>
      <BackupRestorePanel makerspaceId={7} isSuperadmin />
    </ToastProvider></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Disaster restore…" }));
    fireEvent.click(screen.getByRole("button", { name: "Record disaster restore intent" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/platform/restores", {
      method: "POST", body: JSON.stringify({ archive: archiveId, kind: "disaster" }),
    }));
    const instruction = id === restoreId ? `Run scripts/restore.sh ${id} on the privileged deployment host.`
      : "Ask the privileged deployment host operator to run this intent.";
    await waitFor(() => expect(screen.getAllByText(`Restore intent recorded. ${instruction}`)).toHaveLength(2));
    expect(screen.queryByText(/restore completed/i)).not.toBeInTheDocument();
    if (id !== restoreId) expect(screen.queryByText(/scripts\/restore.sh unsafe/)).not.toBeInTheDocument();
  });
});
