import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { memberRequest, tenantPublicRequest, tenantPublicRequestBlob } from "./apiRequests";
import { cacheTenantPublishableKey, tenantPublishableKeys } from "./apiSession";
import { fetchMock, jsonResponse, requestHeaders, resetSessionTransport } from "./apiSessionTestHelpers";

beforeEach(() => {
  resetSessionTransport(accessToken("member-access"));
  tenantPublishableKeys.clear();
  cacheTenantPublishableKey("a", "pk_a");
  cacheTenantPublishableKey("b", "pk_b");
});
afterEach(() => vi.unstubAllGlobals());

describe("cached tenant credential revisit", () => {
  it.each(["JSON", "blob"])("reactivates A on a cached public %s visit before a slugless member request", async (kind) => {
    fetchMock.mockImplementation(async () => jsonResponse(200, { ok: true }));
    const visit = (slug: string) => kind === "JSON"
      ? tenantPublicRequest(slug, `/public/${slug}/tools`)
      : tenantPublicRequestBlob(slug, `/public/${slug}/calendar`);
    await visit("a");
    await visit("b");
    await visit("a");
    await memberRequest("/member/profile");

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls.map((_, index) => requestHeaders(index).get("X-Publishable-Key")))
      .toEqual(["pk_a", "pk_b", "pk_a", "pk_a"]);
    expect(requestHeaders(3).get("Authorization")).toBe(`Bearer ${accessToken("member-access")}`);
    expect(String(fetchMock.mock.calls[3][0])).toMatch(/\/member\/profile$/);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/bootstrap"))).toBe(false);
  });
});
