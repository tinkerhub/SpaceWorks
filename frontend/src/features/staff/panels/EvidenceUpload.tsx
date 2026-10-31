import { useId, useLayoutEffect, useRef, useState } from "react";
import { Camera, CheckCircle2 } from "lucide-react";

import { Button, CameraCapture, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";

import { useAuthActionOwner } from "../../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../../lib/apiSession";
import { admitUpload, uploadBytes } from "../../../lib/uploadProtocol";

type UploadResponse = {
  evidence_id: number;
  upload_url: string;
  fields: Record<string, string>;
  object_key: string;
  method?: string;
  headers?: Record<string, string>;
};

/**
 * Two-step evidence photo upload used by the issue/return flows (hard rule:
 * hardware can't be issued/returned without a photo). Step 1 asks the backend
 * for a presigned POST + an EvidencePhoto row (returns evidence_id). Step 2
 * uploads the file straight to object storage with the presigned fields. The
 * resulting evidence_id is handed back to the parent form via onUploaded.
 */
type EvidenceUploadProps = {
  makerspaceId: number;
  evidenceType: "issue" | "return";
  disabled?: boolean;
  label?: string;
  resourceContext?: string | number | null;
  onUploaded: (evidenceId: number | null) => void;
};

export function EvidenceUpload(props: EvidenceUploadProps) {
  const scope = JSON.stringify([props.makerspaceId, props.evidenceType, props.resourceContext, getSessionGeneration()]);
  return <OwnedEvidenceUpload key={scope} {...props} scope={scope} />;
}

function OwnedEvidenceUpload({ makerspaceId, evidenceType, disabled = false, label, onUploaded, scope }: EvidenceUploadProps & { scope: string }) {
  const owner = useAuthActionOwner(scope);
  const disabledRef = useRef(disabled);
  const onUploadedRef = useRef(onUploaded);
  disabledRef.current = disabled;
  onUploadedRef.current = onUploaded;
  useLayoutEffect(() => {
    // A new semantic widget must clear the parent's old evidence before paint.
    // Cleanup must never clear evidence belonging to the next mounted context.
    if (owner.isContextCurrent()) onUploadedRef.current(null);
  }, [owner.context]);
  const inputId = useId();
  const { showToast } = useToast();
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [cameraOpen, setCameraOpen] = useState<symbol | null>(null);
  const cameraVisit = useRef<symbol | null>(null);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );

  async function handleFile(file: File) {
    if (disabledRef.current || !owner.isIntentCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    const guard = admitUpload(() => owner.isCurrent(action));
    setStatus("uploading");
    setError("");
    setFileName(file.name);
    onUploadedRef.current(null); // invalidate any prior upload until this one completes
    try {
      guard.assertCurrent();
      const presigned = await staffRequest<UploadResponse>(
        `/admin/makerspaces/${makerspaceId}/uploads/evidence-url`,
        {
          method: "POST",
          body: JSON.stringify({ evidence_type: evidenceType, content_type: file.type, size_bytes: file.size }),
        },
      );
      await uploadBytes(file, { ...presigned, url: presigned.upload_url }, guard);
      guard.assertCurrent();
      setStatus("done");
      onUploadedRef.current(presigned.evidence_id);
    } catch (err) {
      if (!owner.isCurrent(action)) return;
      setStatus("error");
      const message = err instanceof Error ? err.message : "Upload failed.";
      setError(message);
      showToast(`Photo upload failed. ${message}`, { tone: "error" });
      onUploadedRef.current(null);
    } finally {
      owner.finish(action);
    }
  }

  function openCamera() {
    if (disabledRef.current || !owner.isIntentCurrent() || owner.isPending()) return;
    const visit = Symbol();
    cameraVisit.current = visit;
    setCameraOpen(visit);
  }
  function closeCamera() {
    if (!owner.isContextCurrent() || cameraVisit.current !== cameraOpen) return;
    cameraVisit.current = null;
    setCameraOpen(null);
  }
  function captureCamera(file: File) {
    if (disabledRef.current || !cameraOpen || cameraVisit.current !== cameraOpen || !owner.isIntentCurrent()) return;
    closeCamera();
    void handleFile(file);
  }

  return (
    <div className="grid min-w-0 gap-1.5">
      {label ? (
        <label className="text-label text-ink" htmlFor={inputId}>
          {label}
        </label>
      ) : null}
      {/* When a visible <label> names the control, aria-label must go: it would override the
          visible text, leaving the accessible name saying something the sighted user never reads. */}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <input
          id={inputId}
          aria-label={label ? undefined : `${evidenceType} photo`}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          disabled={disabled || status === "uploading"}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFile(file);
          }}
          className="block min-w-0 max-w-full flex-[1_1_15rem] text-sm text-ink-muted file:mr-3 file:min-h-9 pointer-coarse:file:min-h-11 file:cursor-pointer file:rounded-full file:border file:border-line-strong file:bg-canvas file:px-3.5 file:py-1.5 file:text-sm file:font-semibold file:text-ink hover:file:bg-subtle disabled:file:cursor-not-allowed disabled:file:text-ink-muted"
        />
        {cameraSupported ? (
          <Button size="sm" startIcon={<Camera />} aria-label={`Take ${label ?? `${evidenceType} photo`}`} disabled={disabled || status === "uploading"} onClick={openCamera}>
            Camera
          </Button>
        ) : null}
      </div>
      <CameraCapture open={cameraOpen !== null} onClose={closeCamera} onCapture={captureCamera} label={label ?? `${evidenceType} photo`} />
      {/* ONE persistent live region, not three conditional ones: a role="status" element that is
          inserted at the same moment its text appears is frequently not announced, because the
          region was not in the DOM for the screen reader to observe changing. */}
      <p
        role="status"
        aria-live="polite"
        className={`flex items-center gap-1.5 break-words text-caption ${status === "error" ? "text-danger-fg" : status === "done" ? "text-success-fg" : "text-ink-muted"}`}
      >
        {status === "done" ? <CheckCircle2 aria-hidden="true" className="size-4 shrink-0" /> : null}
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
