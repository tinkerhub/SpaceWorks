import { afterEach, describe, expect, it, vi } from "vitest";
import { cacheTenantPublishableKey } from "../../lib/api";
import {
  fetchPrintQueues,
  fetchPrintStatus,
  presignPrintUpload,
  submitPrintRequest,
} from "./publicApi";

describe("generic public printer service API", () => {
  afterEach(() => vi.restoreAllMocks());
  it("uses machine-service routes for queues, submission, and token status", async () => {
    cacheTenantPublishableKey("forge", "test-key");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify([]), { status: 200 }));
    await fetchPrintQueues("forge");
    await submitPrintRequest("forge", { title: "Bracket", queue_id: 8, consumable_pool_id: 13, file_ids: [] });
    await fetchPrintStatus("private-token");
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual(expect.arrayContaining([expect.stringContaining("/public/forge/machine-service/3d-printer/queues"), expect.stringContaining("/public/forge/machine-service/3d-printer/requests"), expect.stringContaining("/public/machine-service/3d-printer/requests/private-token/status")]));
    expect(urls.join(" ")).not.toContain("/printing/");
  });

  it("passes checked-in identity through upload and request JSON", async () => {
    cacheTenantPublishableKey("forge", "test-key");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    );

    await presignPrintUpload("forge", {
      kind: "stl",
      filename: "bracket.stl",
      checkin_mid: 443,
      name: "Ada Example",
    });
    await submitPrintRequest("forge", {
      title: "Bracket",
      checkin_mid: 443,
      name: "Ada Example",
    });

    const bodies = fetchMock.mock.calls.map(([, init]) =>
      JSON.parse(String(init?.body)),
    );
    expect(bodies).toEqual([
      expect.objectContaining({ checkin_mid: 443, name: "Ada Example" }),
      expect.objectContaining({ checkin_mid: 443, name: "Ada Example" }),
    ]);
  });
});
