import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, ScanLine } from "lucide-react";

import { Button, Callout, Card, ConfirmDialog, EmptyState, StatusChip, useToast } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { StructuredApiError } from "../../lib/api";
import type {
  OfflineRoster,
  OfflineRosterRegistration,
  QueuedCheckIn,
  SyncResponse,
} from "./eventCheckInOfflineApi";
import {
  applySyncResults,
  loadOfflineState,
  pruneExpiredOfflineStates,
  queueOfflineCheckIn,
  saveOfflineRoster,
  wipeOfflineState,
  type OfflineCheckInState,
} from "./eventCheckInOfflineStore";

export function OfflineCheckInOperator({
  scope,
  download,
  synchronize,
  onSynchronized,
  autoDownload = false,
}: {
  scope: string;
  download: () => Promise<OfflineRoster>;
  synchronize: (roster: OfflineRoster, operations: QueuedCheckIn[]) => Promise<SyncResponse>;
  onSynchronized?: () => void | Promise<void>;
  autoDownload?: boolean;
}) {
  const [state, setState] = useState<OfflineCheckInState | null>(null);
  const [resolved, setResolved] = useState<OfflineRosterRegistration | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [autoAttempted, setAutoAttempted] = useState(false);
  const [confirmWipe, setConfirmWipe] = useState(false);
  const { showToast } = useToast();

  const refresh = useCallback(async () => {
    await pruneExpiredOfflineStates();
    setState(await loadOfflineState(scope));
  }, [scope]);

  const downloadNow = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      setState(await saveOfflineRoster(scope, await download()));
      showToast("Roster saved on this device", { tone: "success" });
    }
    catch (cause) {
      if (cause instanceof StructuredApiError && [400, 403, 410].includes(cause.status)) {
        await wipeOfflineState(scope); setState(null);
      }
      const message = cause instanceof Error ? cause.message : "Could not download roster.";
      showToast(message, { tone: "error" });
      setError(message);
    }
    finally { setBusy(false); }
  }, [download, scope, showToast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const visibility = () => { if (!document.hidden) void refresh(); };
    const connection = () => setOnline(navigator.onLine);
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("online", connection);
    window.addEventListener("offline", connection);
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("online", connection);
      window.removeEventListener("offline", connection);
    };
  }, [refresh]);
  useEffect(() => {
    if (autoDownload && !state && !busy && !autoAttempted) {
      setAutoAttempted(true);
      void downloadNow();
    }
  }, [autoAttempted, autoDownload, busy, downloadNow, state]);

  function handleScan(value: string) {
    setScanning(false); setError(null);
    if (!state || Date.now() > Date.parse(state.roster.expires_at)) {
      setError("The offline roster expired. Download it again."); return;
    }
    const match = state.roster.registrations.find(
      (row) => row.checkin_token.toLowerCase() === value.trim().toLowerCase(),
    );
    if (!match) { setError("That is not a check-in code for this event."); return; }
    setResolved(match);
  }

  async function confirm() {
    if (!resolved || !state) return;
    const now = new Date();
    if (now > new Date(state.roster.scan_closes_at)) {
      setError("The event check-in window has closed."); return;
    }
    const operation: QueuedCheckIn = {
      operation_id: crypto.randomUUID(),
      checkin_token: resolved.checkin_token,
      reported_occurred_at: now.toISOString(),
    };
    try {
      setState(await queueOfflineCheckIn(scope, operation));
      showToast(`${resolved.name} checked in — queued to sync`, { tone: "success" });
      setResolved(null);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not queue attendance.";
      showToast(message, { tone: "error" });
      setError(message);
    }
  }

  async function syncNow() {
    if (!state?.operations.length) return;
    setBusy(true); setError(null);
    try {
      const response = await synchronize(state.roster, state.operations);
      setState(await applySyncResults(scope, response.results, response.recorded_at));
      showToast("Check-ins synchronized", { tone: "success" });
      await onSynchronized?.();
    } catch (cause) {
      if (cause instanceof StructuredApiError && [400, 403, 410].includes(cause.status)) {
        await wipeOfflineState(scope); setState(null);
      }
      const message = cause instanceof Error ? cause.message : "Could not synchronize check-ins.";
      showToast(message, { tone: "error" });
      setError(message);
    } finally { setBusy(false); }
  }

  async function wipe() {
    await wipeOfflineState(scope);
    setState(null); setResolved(null); setScanning(false); setError(null);
    showToast("Attendee data wiped from this device", { tone: "success" });
  }

  return (
    <Card as="section" padding="sm" className="grid gap-3" aria-labelledby={`${scope}-offline-title`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 id={`${scope}-offline-title`} className="text-title text-ink">Offline-ready check-in</h4>
            <StatusChip tone={online ? "success" : "warning"} size="sm">{online ? "Online" : "Offline"}</StatusChip>
          </div>
          <p className="mt-1 text-caption text-ink-muted">Attendee names are encrypted on this device.</p>
        </div>
        <Button size="sm" startIcon={<Download />} loading={busy} onClick={downloadNow}>
          {state ? "Refresh roster" : "Download roster"}
        </Button>
      </div>
      {state ? (
        <div className="grid gap-3">
          <dl className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-2 text-body-ui">
            <div className="rounded-md bg-subtle px-3 py-2"><dt className="text-caption text-ink-muted">Queued</dt><dd className="font-semibold text-ink">{state.operations.length}</dd></div>
            <div className="rounded-md bg-subtle px-3 py-2"><dt className="text-caption text-ink-muted">Roster expires</dt><dd className="text-ink">{new Date(state.roster.expires_at).toLocaleString()}</dd></div>
            <div className="rounded-md bg-subtle px-3 py-2"><dt className="text-caption text-ink-muted">Last sync</dt><dd className="text-ink">{state.lastSyncedAt ? new Date(state.lastSyncedAt).toLocaleString() : "Never"}</dd></div>
          </dl>
          <p className="text-caption text-ink-muted">Keep this page open while disconnected. Closing or reloading cannot reopen it offline in this release.</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" startIcon={<ScanLine />} onClick={() => setScanning(true)}>Scan offline</Button>
            <Button startIcon={<RefreshCw />} disabled={!online || busy || !state.operations.length} onClick={syncNow}>Synchronize</Button>
            <Button variant="danger" onClick={() => setConfirmWipe(true)}>Wipe attendee data…</Button>
          </div>
          <p aria-live="polite" className="sr-only">{state.operations.length} queued check-ins. {state.conflicts.length} conflicts.</p>
          {state.conflicts.length ? (
            <Callout tone="warning" role="alert" title={`${state.conflicts.length} synchronization conflicts`}>
              <ul className="mt-1 list-disc pl-5">{state.conflicts.map((item) => <li key={item.operation_id}>{item.outcome.replace(/_/g, " ")}</li>)}</ul>
            </Callout>
          ) : null}
        </div>
      ) : (
        <EmptyState title="No attendee data on this device" description="Download the roster before the doors open so check-in keeps working without a connection." />
      )}
      {resolved ? (
        <div className="grid gap-2 rounded-md border border-line p-3">
          <p className="text-label text-ink">{resolved.name}</p>
          <p className="text-body-ui text-ink-muted">Waiver: {resolved.host_waiver_state.replace(/_/g, " ")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={confirm}>Confirm attendance</Button>
            <Button onClick={() => setResolved(null)}>Cancel</Button>
          </div>
        </div>
      ) : null}
      {error ? <Callout tone="danger" role="alert">{error}</Callout> : null}
      {scanning ? <QrScanner onScan={handleScan} onClose={() => setScanning(false)} /> : null}
      <ConfirmDialog
        open={confirmWipe}
        title="Wipe attendee data?"
        message="The roster and any check-ins not yet synchronized are deleted from this device. Synchronize first if you can."
        confirmLabel="Wipe data"
        tone="danger"
        onCancel={() => setConfirmWipe(false)}
        onConfirm={() => { setConfirmWipe(false); void wipe(); }}
      />
    </Card>
  );
}
