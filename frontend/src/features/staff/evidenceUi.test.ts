import { describe, expect, it } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { evidenceErrorText, isQrNotRecognised, QR_NOT_RECOGNISED, qrResolveErrorText } from "./evidenceUi";


describe("evidenceErrorText", () => {
  it("turns terminal retention responses into an explicit expired-photo message", () => {
    const result = evidenceErrorText(new StructuredApiError(410, {
      code: "evidence_expired",
      object_expired_at: "2026-09-02T10:00:00Z",
    }));

    expect(result).toMatch(/^Photo expired on .+ under retention policy\.$/);
    // Times never show seconds.
    expect(result).not.toMatch(/\d{1,2}:\d{2}:\d{2}/);
  });

  it("preserves ordinary evidence failures", () => {
    expect(evidenceErrorText(new Error("Storage unavailable"))).toBe(
      "Storage unavailable",
    );
  });
});

describe("qrResolveErrorText", () => {
  it("reads a tenant-origin 403 exactly like a 404: not recognised on this site", () => {
    const forbidden = new StructuredApiError(403, { detail: "You do not have permission to perform this action." });
    const missing = new StructuredApiError(404, { detail: "Not found." });

    expect(isQrNotRecognised(forbidden)).toBe(true);
    expect(qrResolveErrorText(forbidden)).toBe(QR_NOT_RECOGNISED);
    expect(qrResolveErrorText(missing)).toBe(QR_NOT_RECOGNISED);
    expect(QR_NOT_RECOGNISED).toBe("QR code not recognised on this site.");
  });

  it("keeps other failures in their own words", () => {
    expect(isQrNotRecognised(new StructuredApiError(400, { detail: "Bad payload." }))).toBe(false);
    expect(qrResolveErrorText(new StructuredApiError(400, { detail: "Bad payload." }))).toBe("Bad payload.");
    expect(qrResolveErrorText("boom", "Could not read that QR.")).toBe("Could not read that QR.");
  });
});
