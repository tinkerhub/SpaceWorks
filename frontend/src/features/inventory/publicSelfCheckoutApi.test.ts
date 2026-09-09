import { afterEach, describe, expect, it, vi } from "vitest";

import { cacheTenantPublishableKey } from "../../lib/api";
import { publicToolCheckout, publicToolReturn } from "./api";
import { requestPublicEvidenceUpload } from "./selfCheckoutApi";

describe("public self-checkout identity API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("passes checked-in identity through evidence, checkout, and return JSON", async () => {
    cacheTenantPublishableKey("forge", "test-key");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    );
    const identity = { checkin_mid: 443, name: "Ada Example" };

    await requestPublicEvidenceUpload("forge", {
      evidence_type: "issue",
      content_type: "image/jpeg",
      size_bytes: 5,
      ...identity,
    });
    await publicToolCheckout("forge", {
      payload: "tool-qr-token",
      evidence_id: 91,
      ...identity,
    });
    await publicToolReturn("forge", {
      payload: "tool-qr-token",
      evidence_id: 92,
      remark: "Returned clean",
      ...identity,
    });

    const bodies = fetchMock.mock.calls.map(([, init]) =>
      JSON.parse(String(init?.body)),
    );
    expect(bodies).toHaveLength(3);
    for (const body of bodies) {
      expect(body).toMatchObject(identity);
    }
  });

  it("does not add identity keys to legacy request bodies", async () => {
    cacheTenantPublishableKey("forge", "test-key");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    );

    await publicToolCheckout("forge", {
      payload: "tool-qr-token",
      evidence_id: 91,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      payload: "tool-qr-token",
      evidence_id: 91,
    });
  });
});
