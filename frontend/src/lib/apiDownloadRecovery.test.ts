import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "./apiErrors";
import { downloadStaffFile, tenantPublicRequestBlob } from "./apiRequests";
import { addAuthExpiredListener, getAccessToken, logout } from "./apiSession";
import { fetchMock, heldResponse, jsonResponse, requestHeaders, resetSessionTransport } from "./apiSessionTestHelpers";

const createObjectURL = vi.fn<(blob: Blob) => string>();
const revokeObjectURL = vi.fn<(url: string) => void>();
const expired = vi.fn();
const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
let unsubscribe: () => void;
let clicked: { href: string; filename: string }[];

beforeEach(() => {
  resetSessionTransport();
  expired.mockReset();
  unsubscribe = addAuthExpiredListener(expired);
  createObjectURL.mockReset().mockReturnValue("blob:http://localhost/report");
  revokeObjectURL.mockReset();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, filename: this.download });
  });
});
afterEach(() => {
  unsubscribe();
  vi.restoreAllMocks();
  if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
  vi.unstubAllGlobals();
});

const bytes = new Uint8Array([0, 255, 80, 75, 13, 10, 128, 42]);
function binaryResponse(type: string) {
  return new Response(bytes, { status: 200, headers: { "Content-Type": type } });
}
async function expectBinary(blob: Blob, type: string) {
  expect(blob.type).toBe(type);
  expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes));
}

describe("staff binary download recovery", () => {
  it.each([
    ["CSV", "text/csv", "loans.csv"],
    ["XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "loans.xlsx"],
    ["ZIP", "application/zip", "evidence.zip"],
  ])("downloads exact %s bytes once after refreshing a stale bearer", async (_kind, type, filename) => {
    const unauthorized = jsonResponse(401, { detail: "Expired token: never download this body" });
    const errorBlob = vi.spyOn(unauthorized, "blob");
    fetchMock.mockResolvedValueOnce(unauthorized)
      .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("fresh-access") }))
      .mockResolvedValueOnce(binaryResponse(type));
    await downloadStaffFile("/admin/reports/export", filename);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/auth\/refresh$/);
    expect(fetchMock.mock.calls[2][0]).toBe(fetchMock.mock.calls[0][0]);
    expect(requestHeaders(0).get("Authorization")).toBe(`Bearer ${accessToken("old-access")}`);
    expect(requestHeaders(2).get("Authorization")).toBe(`Bearer ${accessToken("fresh-access")}`);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    await expectBinary(createObjectURL.mock.calls[0][0], type);
    expect(clicked).toEqual([{ href: "blob:http://localhost/report", filename }]);
    expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:http://localhost/report");
    expect(errorBlob).not.toHaveBeenCalled();
    expect(expired).not.toHaveBeenCalled();
  });

  it.each([403, 404])("rejects a typed %i without refresh or file side effects", async (status) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(status, { detail: "Not downloadable" }));
    const request = downloadStaffFile("/admin/reports/export", "report.csv");
    await expect(request).rejects.toBeInstanceOf(StructuredApiError);
    await expect(request).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clicked).toEqual([]);
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });

  it("expires the session on failed refresh without downloading the error", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(401));
    await expect(downloadStaffFile("/admin/reports/export", "report.zip")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe("");
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clicked).toEqual([]);
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });
});

describe("tenant public calendar binary recovery", () => {
  it.each(["refresh", "anonymous fallback"])("preserves the tenant key and calendar bytes via %s", async (recovery) => {
    const refreshed = recovery === "refresh";
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(refreshed ? 200 : 401, { access: accessToken("calendar-access") }))
      .mockResolvedValueOnce(binaryResponse("text/calendar"));
    const blob = await tenantPublicRequestBlob("forge", "/public/forge/events/calendar.ics");
    await expectBinary(blob, "text/calendar");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(requestHeaders(0).get("X-Publishable-Key")).toBe("pk_forge");
    expect(requestHeaders(2).get("X-Publishable-Key")).toBe("pk_forge");
    expect(requestHeaders(0).get("Authorization")).toBe(`Bearer ${accessToken("old-access")}`);
    expect(requestHeaders(2).get("Authorization")).toBe(refreshed ? `Bearer ${accessToken("calendar-access")}` : null);
    expect(fetchMock.mock.calls[2][0]).toBe(fetchMock.mock.calls[0][0]);
    expect(expired).not.toHaveBeenCalled();
  });

  it("cannot resurrect a calendar session after logout while refresh is pending", async () => {
    const held = heldResponse();
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockImplementationOnce(held.send);
    const request = tenantPublicRequestBlob("forge", "/public/forge/events/calendar.ics");
    const rejection = expect(request).rejects.toMatchObject({ status: 401 });
    await held.entered;
    fetchMock.mockResolvedValueOnce(jsonResponse(204));
    await logout();
    held.resolve(jsonResponse(200, { access: accessToken("obsolete-calendar-access") }));
    await rejection;
    expect(getAccessToken()).toBe("");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(expired).not.toHaveBeenCalled();
  });
});
