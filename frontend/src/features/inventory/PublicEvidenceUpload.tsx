import { useLayoutEffect, useRef, useState } from "react";

import { Camera } from "lucide-react";

import { Button, CameraCapture } from "../../components/ui";
import {
  requestPublicEvidenceUpload,
  uploadPublicEvidenceFile,
} from "./selfCheckoutApi";
import type { CheckinMatch } from "./api";
import { getSessionGeneration } from "../../lib/apiSession";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";

type Props = {
  slug: string;
  evidenceType: "issue" | "return";
  checkinIdentity?: Pick<CheckinMatch, "mid" | "name">;
  disabled?: boolean;
  onUploaded: (evidenceId: number | null) => void;
};

export function PublicEvidenceUpload(props: Props) {
  const scope = JSON.stringify([props.slug, props.evidenceType, props.checkinIdentity?.mid,
    props.checkinIdentity?.name, getSessionGeneration()]);
  // Remount native file/camera state before any new semantic context can paint.
  return <OwnedEvidenceUpload key={scope} {...props} scope={scope} />;
}

function OwnedEvidenceUpload({ slug, evidenceType, checkinIdentity, disabled = false, onUploaded, scope }: Props & { scope: string }) {
  const owner = useAuthActionOwner(scope);
  const latest = useRef({ disabled, onUploaded });
  latest.current = { disabled, onUploaded };
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const activeCamera = useRef<AuthAction | null>(null);
  const [cameraAction, setCameraAction] = useState<AuthAction | null>(null);
  const cameraOpen = cameraAction !== null && owner.isCurrent(cameraAction);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );
  const label = evidenceType === "issue" ? "Issue photo" : "Return photo";

  useLayoutEffect(() => {
    if (owner.isContextCurrent()) latest.current.onUploaded(null);
    // A callback change is not a new evidence context. Unmount never clears a parent.
  }, [owner.context]);

  async function handleFile(file: File, camera?: AuthAction | null) {
    if (latest.current.disabled || (camera !== undefined &&
      (!owner.isCurrent(camera) || activeCamera.current !== camera))) return;
    const action = owner.begin();
    if (!action) return;
    const input = {
      slug, file,
      body: {
        evidence_type: evidenceType,
        content_type: file.type,
        size_bytes: file.size,
        ...(checkinIdentity ? { checkin_mid: checkinIdentity.mid, name: checkinIdentity.name } : {}),
      },
    };
    activeCamera.current = null;
    setCameraAction(null);
    setStatus("uploading");
    setError("");
    setFileName(file.name);
    latest.current.onUploaded(null);
    try {
      if (!owner.isCurrent(action)) return;
      const presigned = await requestPublicEvidenceUpload(input.slug, input.body);
      if (!owner.isCurrent(action)) return;
      // Already-admitted storage bytes may finish; obsolete work cannot publish evidence.
      await uploadPublicEvidenceFile(presigned, input.file);
      if (!owner.isCurrent(action)) return;
      setStatus("done");
      latest.current.onUploaded(presigned.evidence_id);
    } catch (err) {
      if (!owner.isCurrent(action)) return;
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed.");
      latest.current.onUploaded(null);
    } finally {
      owner.finish(action);
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
          <Button className="shrink-0" aria-label={`Take ${label}`} startIcon={<Camera />} disabled={disabled || status === "uploading"} onClick={() => {
            if (latest.current.disabled || owner.isPending()) return;
            const action = owner.capture();
            if (!action) return;
            activeCamera.current = action; setCameraAction(action);
          }}>
            Camera
          </Button>
        ) : null}
      </div>
      <CameraCapture open={cameraOpen}
        onClose={() => {
          if (owner.isCurrent(cameraAction) && activeCamera.current === cameraAction) {
            activeCamera.current = null; setCameraAction(null);
          }
        }}
        onCapture={(file) => { void handleFile(file, cameraAction); }} label={label} />
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
