import { StructuredApiError } from "../../lib/api";

/** Plain words for a failed evidence-photo fetch; an expired photo (410) says when. */
export function evidenceErrorText(error: unknown) {
  if (error instanceof StructuredApiError && error.status === 410) {
    const expiredAt = error.body.object_expired_at;
    const when = typeof expiredAt === "string"
      ? new Date(expiredAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
      : "an unknown date";
    return `Photo expired on ${when} under retention policy.`;
  }
  return error instanceof Error ? error.message : "Could not load evidence photo.";
}

export const QR_NOT_RECOGNISED = "QR code not recognised on this site.";

/** True when /admin/qr/resolve (or /admin/qr/scan) did not find the code for this site. */
export function isQrNotRecognised(error: unknown) {
  // On a tenant origin the server answers an unknown code AND another makerspace's code
  // with the same generic 403 (telling them apart would leak that the code exists
  // elsewhere), so 403 reads exactly like 404 here, never as a permission problem.
  return error instanceof StructuredApiError && (error.status === 403 || error.status === 404);
}

/** Plain words for a failed QR resolve/scan. */
export function qrResolveErrorText(error: unknown, fallback = "Could not read that QR code. Try again.") {
  if (isQrNotRecognised(error)) return QR_NOT_RECOGNISED;
  return error instanceof Error && error.message ? error.message : fallback;
}
