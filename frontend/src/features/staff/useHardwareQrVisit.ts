import { useRef, useState } from "react";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";

type Scan = { action: AuthAction; editable: () => boolean; camera?: number };

// Asset scans share a form visit, not a latest-wins sequence: two valid held scans both count.
// Camera callbacks additionally retain the particular scanner opening that supplied them.
export function useHardwareQrVisit(scope: string, editable: () => boolean) {
  const owner = useAuthActionOwner(scope);
  const latestEditable = useRef(editable);
  latestEditable.current = editable;
  const camera = useRef(0);
  const [cameraVisit, setCameraVisit] = useState(0);
  const consumedCamera = useRef<number | null>(null);
  const canEdit = () => owner.isIntentCurrent() && editable() && latestEditable.current();
  const cameraCurrent = (visit?: number) => visit === undefined || visit === camera.current;
  function capture(visit?: number): Scan | null {
    if (!canEdit() || !cameraCurrent(visit)) return null;
    const action = owner.capture();
    return action ? { action, editable, camera: visit } : null;
  }
  function captureSingleCamera(visit: number) {
    if (consumedCamera.current === visit) return null;
    const scan = capture(visit);
    if (scan) consumedCamera.current = visit;
    return scan;
  }
  function current(scan: Scan | null): scan is Scan {
    return Boolean(scan && owner.isCurrent(scan.action) && scan.editable() &&
      latestEditable.current() && cameraCurrent(scan.camera));
  }
  return {
    canEdit, capture, captureSingleCamera, current, cameraVisit, cameraCurrent,
    openCamera: () => { if (canEdit()) { camera.current += 1; setCameraVisit(camera.current); } },
    closeCamera: () => { camera.current += 1; },
  };
}
