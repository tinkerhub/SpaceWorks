import { useEffect, useId, useRef, useState } from "react";
import { Camera, ImageIcon } from "lucide-react";

import { Button, CameraCapture, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";

import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../lib/apiSession";
import { admitUpload } from "../../lib/uploadProtocol";
import { uploadPublicImage } from "./imageUploadApi";
export { uploadPublicImage } from "./imageUploadApi";

type ImageUploaderProps = {
  /** Admin endpoint base, e.g. `/admin/inventory/12/image` or `/admin/makerspace/3/logo`. */
  endpoint: string;
  /** Current public image URL (preview), or null/empty when none. */
  currentUrl?: string | null;
  label: string;
  /** Called after a successful attach or clear so the parent can refetch. */
  onChanged: () => void;
  disabled?: boolean;
  /** object-contain (logos) vs object-cover (photos). */
  fit?: "cover" | "contain";
  /** square preview (logos/thumbnails) vs wide banner preview (cover images). */
  shape?: "square" | "wide";
  /** Extra fields sent with presign, attach and clear (e.g. `{ project_id }`). */
  extraBody?: Record<string, unknown>;
  /** Query string appended to the clear request, which carries no body. */
  clearQuery?: string;
};

/**
 * Reusable public-image uploader for staff (item photos, makerspace logo/cover).
 * Drives the Phase-2 flow: POST -> presign, upload via the returned method
 * (POST multipart or PUT), then PUT { object_key } to finalize+attach. The
 * storage upload itself is an unauthenticated direct-to-bucket request.
 */
export function ImageUploader(props: ImageUploaderProps) {
  const scope = JSON.stringify([props.endpoint, props.clearQuery ?? "", props.extraBody ?? {}, getSessionGeneration()]);
  return <OwnedImageUploader key={scope} {...props} scope={scope} />;
}

function OwnedImageUploader({
  endpoint,
  currentUrl,
  label,
  onChanged,
  disabled = false,
  fit = "cover",
  shape = "square",
  extraBody,
  clearQuery = "",
  scope,
}: ImageUploaderProps & { scope: string }) {
  const owner = useAuthActionOwner(scope);
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;
  const inputId = useId();
  const objectUrlRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Cover images are wide banners - give them a rectangular preview that matches
  // how they render publicly, instead of cropping into an 80x80 square.
  const previewBox = shape === "wide" ? "h-24 w-full max-w-full sm:h-20 sm:w-44" : "h-20 w-20";
  const { showToast } = useToast();
  const [status, setStatus] = useState<"idle" | "uploading" | "error">("idle");
  const [error, setError] = useState("");
  const [cameraOpen, setCameraOpen] = useState<symbol | null>(null);
  const cameraVisit = useRef<symbol | null>(null);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );
  // Drive the preview from local state so an upload/remove reflects immediately,
  // even though the parent's `currentUrl` (a snapshot) only refreshes on its next
  // refetch. Re-sync whenever the parent does send a new URL.
  const [preview, setPreview] = useState<string | null>(currentUrl ?? null);
  useEffect(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setPreview(currentUrl ?? null);
  }, [currentUrl]);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  function setLocalPreview(file: File) {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = URL.createObjectURL(file);
    setPreview(objectUrlRef.current);
  }

  const busy = disabled || status === "uploading";

  async function handleFile(file: File) {
    if (disabledRef.current || !owner.isIntentCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    const guard = admitUpload(() => owner.isCurrent(action));
    setStatus("uploading");
    setError("");
    try {
      await uploadPublicImage(endpoint, file, extraBody, guard);
      guard.assertCurrent();
      setStatus("idle");
      setLocalPreview(file);
      showToast(`${label} updated`, { tone: "success" });
      onChanged();
    } catch (err) {
      if (!owner.isCurrent(action)) return;
      setStatus("error");
      const message = err instanceof Error ? err.message : "Upload failed.";
      setError(message);
      showToast(message, { tone: "error" });
    } finally {
      if (owner.isCurrent(action) && inputRef.current) inputRef.current.value = "";
      owner.finish(action);
    }
  }

  async function clearImage() {
    if (disabledRef.current || !owner.isIntentCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    const guard = admitUpload(() => owner.isCurrent(action));
    setStatus("uploading");
    setError("");
    try {
      guard.assertCurrent();
      await staffRequest(`${endpoint}${clearQuery}`, { method: "DELETE" });
      guard.assertCurrent();
      setStatus("idle");
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
      setPreview(null);
      showToast(`${label} removed`, { tone: "success" });
      onChanged();
    } catch (err) {
      if (!owner.isCurrent(action)) return;
      setStatus("error");
      const message = err instanceof Error ? err.message : "Could not remove image.";
      setError(message);
      showToast(message, { tone: "error" });
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
    <div className="grid min-w-0 gap-2">
      <label htmlFor={inputId} className="text-label text-ink">{label}</label>
      <div className="flex min-w-0 flex-wrap items-start gap-4">
        <div className={`${previewBox} shrink-0 overflow-hidden rounded-md border border-line bg-subtle`}>
          {preview ? (
            <img
              src={preview}
              alt={label}
              className={`h-full w-full ${fit === "contain" ? "object-contain" : "object-cover"}`}
            />
          ) : (
            <div className="grid h-full w-full place-items-center text-ink-muted" aria-hidden="true">
              <ImageIcon className="size-6" />
            </div>
          )}
        </div>
        <div className="grid min-w-0 max-w-full flex-[1_1_16rem] gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <input
              id={inputId}
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) handleFile(file);
              }}
              className="block min-w-0 max-w-full flex-[1_1_15rem] text-sm text-ink-muted file:mr-3 file:min-h-9 pointer-coarse:file:min-h-11 file:cursor-pointer file:rounded-full file:border file:border-line-strong file:bg-canvas file:px-3.5 file:py-1.5 file:text-sm file:font-semibold file:text-ink hover:file:bg-subtle disabled:file:cursor-not-allowed disabled:file:text-ink-muted"
            />
            {cameraSupported ? (
              <Button size="sm" startIcon={<Camera />} aria-label={`Take ${label} photo`} disabled={busy} onClick={openCamera}>
                Camera
              </Button>
            ) : null}
          </div>
          <CameraCapture open={cameraOpen !== null} onClose={closeCamera} onCapture={captureCamera} label={label} />
          <p className="text-caption text-ink-muted">JPEG, PNG or WebP.</p>
          {preview ? (
            <div>
              <Button size="sm" variant="danger-quiet" disabled={busy} onClick={clearImage}>
                Remove
              </Button>
            </div>
          ) : null}
          {/* ONE persistent live region, not two conditional ones: a role="status" element that is
              inserted at the same moment its text appears is frequently not announced, because the
              region was not in the DOM for the screen reader to observe changing. */}
          <p
            role="status"
            aria-live="polite"
            className={status === "error" ? "break-words text-caption text-danger-fg" : "break-words text-caption text-ink-muted"}
          >
            {status === "uploading" ? "Working…" : status === "error" ? error : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
