import type React from "react";
import { useEffect, useState } from "react";
import { QrCode } from "lucide-react";

import QrScanner from "../../../components/ui/QrScanner";
import { Button, Chip, Dropdown, Field, Input } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { qrResolveErrorText } from "../evidenceUi";

export function BoxCodeField({ value, onChange, makerspaceId, pending }: { value: string; onChange: (code: string) => void; makerspaceId: number; pending: boolean }) {
  const [containers, setContainers] = useState<ContainerOption[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [scanned, setScanned] = useState<{ code: string; label: string } | null>(null);
  const [scanOpen, setScanOpen] = useState(false);
  const [scanError, setScanError] = useState("");
  const [manualOpen, setManualOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoadError(false);
    staffRequest<{ results: ContainerOption[] }>(`/admin/makerspace/${makerspaceId}/containers?page_size=1000`)
      .then((res) => {
        if (!cancelled) setContainers((res.results ?? []).filter((c) => c.is_active !== false && c.code));
      })
      .catch(() => {
        if (!cancelled) {
          setContainers([]);
          setLoadError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [makerspaceId]);

  const listed = containers.find((container) => container.code === value);
  const displayLabel = listed?.label ?? (scanned && scanned.code === value ? scanned.label : "");

  const handleScan = async (payload: string) => {
    setScanOpen(false);
    const clean = payload.trim();
    if (!clean) return;
    try {
      const res = await staffRequest<{ target: { type: string; code?: string; label?: string } }>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: clean }),
      });
      if (res.target.type === "box" && res.target.code) {
        onChange(res.target.code);
        setScanned({ code: res.target.code, label: res.target.label ?? "" });
        setScanError("");
      } else {
        setScanError("That QR isn't a box or container. Scan the container's label.");
      }
    } catch (error) {
      setScanError(qrResolveErrorText(error, "Could not read that QR. Try again, or pick the container from the list."));
    }
  };

  return (
    <div className="grid gap-3">
      <div className="grid gap-1.5">
        <span className="text-label text-ink">Container</span>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-subtle px-3.5 py-2">
            <span className={value ? "min-w-0 truncate font-semibold text-ink" : "min-w-0 truncate text-ink-muted"}>{value ? displayLabel || value : "No container selected"}</span>
            {value ? <Chip tone="success" size="sm">Selected</Chip> : null}
          </div>
          <Button startIcon={<QrCode />} disabled={pending} onClick={() => setScanOpen(true)}>Scan</Button>
        </div>
      </div>
      {containers.length ? (
        <Field label="Available container">
          <Dropdown value={listed ? value : ""} disabled={pending} onChange={(event) => event.target.value && onChange(event.target.value)}>
            <option value="" disabled>Choose an available container…</option>
            {containers.map((container) => <option key={container.id} value={container.code ?? ""}>{container.label}</option>)}
          </Dropdown>
        </Field>
      ) : null}
      {loadError ? <p className="text-caption text-ink-muted">Couldn't load the container list. Scan the box or enter its code.</p> : null}
      <Button variant="quiet" size="sm" className="justify-self-start" disabled={pending} onClick={() => setManualOpen((open) => !open)}>
        {manualOpen ? "Hide manual code entry" : "Enter code manually"}
      </Button>
      {manualOpen ? <Field label="Container code"><Input className="font-mono" value={value} disabled={pending} onChange={(event) => onChange(event.target.value)} /></Field> : null}
      {scanError ? <p role="alert" className="text-caption text-danger-fg">{scanError}</p> : null}
      {scanOpen ? <QrScanner onScan={handleScan} onClose={() => setScanOpen(false)} /> : null}
    </div>
  );
}

export function FormFooter({ formId, pending, submitLabel, tone = "default", onCancel }: { formId: string; pending: boolean; submitLabel: string; tone?: "danger" | "default"; onCancel: () => void }) {
  return (
    <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
      <Button variant="secondary" disabled={pending} onClick={onCancel}>Cancel</Button>
      <Button variant={tone === "danger" ? "danger" : "primary"} type="submit" form={formId} loading={pending}>{submitLabel}</Button>
    </div>
  );
}

// The product's free-text storage location ("shelf") so staff know where to physically
// fetch or return the item during handover. Renders nothing when no shelf is recorded.
export function ShelfLine({ location }: { location?: string | null }) {
  return location ? (
    <p className="text-caption text-ink-muted">Shelf: <span className="font-semibold text-ink">{location}</span></p>
  ) : null;
}

export function submitForm(event: React.FormEvent<HTMLFormElement>, submit: () => void) {
  event.preventDefault();
  submit();
}

type ContainerOption = { id: number; code?: string | null; label: string; is_active?: boolean };
