import { useEffect, useState } from "react";

import { Camera } from "lucide-react";

import { Button, CameraCapture } from "../../components/ui";
import {
  requestPublicEvidenceUpload,
  uploadPublicEvidenceFile,
} from "./selfCheckoutApi";
import type { CheckinMatch } from "./api";

export function PublicEvidenceUpload({
  slug,
  evidenceType,
  checkinIdentity,
  disabled = false,
  onUploaded,
}: {
  slug: string;
  evidenceType: "issue" | "return";
  checkinIdentity?: Pick<CheckinMatch, "mid" | "name">;
  disabled?: boolean;
  onUploaded: (evidenceId: number | null) => void;
}) {
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );
  const label = evidenceType === "issue" ? "Issue photo" : "Return photo";

  useEffect(() => {
    setStatus("idle");
    setError("");
    setFileName("");
    setCameraOpen(false);
    onUploaded(null);
  }, [evidenceType, onUploaded]);

  async function handleFile(file: File) {
    setStatus("uploading");
    setError("");
    setFileName(file.name);
    onUploaded(null);
    try {
      const presigned = await requestPublicEvidenceUpload(slug, {
        evidence_type: evidenceType,
        content_type: file.type,
        size_bytes: file.size,
        ...(checkinIdentity
          ? {
              checkin_mid: checkinIdentity.mid,
              name: checkinIdentity.name,
            }
          : {}),
      });
      await uploadPublicEvidenceFile(presigned, file);
      setStatus("done");
      onUploaded(presigned.evidence_id);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed.");
      onUploaded(null);
    }
  }

  return (
    <div className="min-w-0 space-y-1">
      <div className="flex min-w-0 flex-wrap items-end gap-2">
        <label className="grid min-w-0 max-w-full flex-[1_1_12rem] gap-1.5">
          <span className="text-label text-ink">{label}</span>
          <input
            aria-label={label}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={disabled || status === "uploading"}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFile(file);
            }}
            className="block min-h-11 w-full rounded-md border border-line-strong bg-canvas p-1 text-sm text-ink-muted file:mr-3 file:min-h-9 file:rounded-full file:border-0 file:bg-fill file:px-3.5 file:py-1.5 file:text-sm file:font-semibold file:text-ink hover:file:bg-emphasis focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60"
          />
        </label>
        {cameraSupported ? (
          <Button className="shrink-0" aria-label={`Take ${label}`} startIcon={<Camera />} disabled={disabled || status === "uploading"} onClick={() => setCameraOpen(true)}>
            Camera
          </Button>
        ) : null}
      </div>
      <CameraCapture open={cameraOpen} onClose={() => setCameraOpen(false)} onCapture={(file) => { void handleFile(file); }} label={label} />
      {/* ONE persistent live region, not three conditional ones: a role="status" element that is
          inserted at the same moment its text appears is frequently not announced, because the
          region was not in the DOM for the screen reader to observe changing. */}
      <p
        role="status"
        aria-live="polite"
        className={`break-words text-caption ${status === "error" ? "text-danger-fg" : status === "done" ? "text-success-fg" : "text-ink-muted"}`}
      >
        {status === "uploading"
          ? `Uploading ${fileName}…`
          : status === "done"
            ? "Photo uploaded"
            : status === "error"
              ? error
              : ""}
      </p>
    </div>
  );
}
