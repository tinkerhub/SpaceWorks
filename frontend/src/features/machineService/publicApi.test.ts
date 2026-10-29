import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cacheTenantPublishableKey, clearAccessToken } from "../../lib/api";
import { fetchServiceStatus, fetchServiceTypes, presignServiceUpload, serviceRequestPath, submitServiceRequest } from "./publicApi";
import { genericType, printerType } from "./serviceTestFixtures";

beforeEach(() => { clearAccessToken(); window.localStorage.clear(); });
afterEach(() => vi.restoreAllMocks());

describe("uniform public service API", () => {
  it.each(["central", "single"])("walks all catalog pages on %s deployments without following absolute next URLs", async (deployment) => {
    cacheTenantPublishableKey("forge", "pk-forge");
    const pages = [
      { count: 3, results: [genericType], next: "https://api.example.test/api/v1/public/forge/machine-service/types?page=2" },
      { count: 3, results: [printerType], next: "https://api.example.test/api/v1/public/forge/machine-service/types?page=3" },
      { count: 3, results: [{ ...genericType, id: 33 }], next: null },
    ];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(pages.shift()), { status: 200 }));
    expect(await fetchServiceTypes("forge")).toEqual([genericType, printerType, { ...genericType, id: 33 }]);
    expect(fetchMock.mock.calls.map(([url]) => new URL(String(url), "https://frontend.test").pathname + new URL(String(url), "https://frontend.test").search)).toEqual([
      "/api/v1/public/forge/machine-service/types?page=1", "/api/v1/public/forge/machine-service/types?page=2", "/api/v1/public/forge/machine-service/types?page=3",
    ]);
    // Only the route prefix changes by deployment; the API remains tenant-explicit.
    expect(serviceRequestPath((path = "") => deployment === "central" ? `/m/forge/${path}` : `/${path}`, 22))
      .toBe(deployment === "central" ? "/m/forge/machine-service?type=22" : "/machine-service?type=22");
  });

  it("sends typed uploads, queue pins and identity to the shared paths and token status to its opaque route", async () => {
    cacheTenantPublishableKey("forge", "pk-forge");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 200 }));
    await presignServiceUpload("forge", { machine_type_id: 22, kind: "stl", filename: "part.stl", queue_id: 8, checkin_mid: 443, name: "Ada" });
    await submitServiceRequest("forge", { machine_type_id: 22, title: "Part", queue_id: 8, file_ids: [17], checkin_mid: 443, name: "Ada" });
    await fetchServiceStatus("private-token");
    expect(fetchMock.mock.calls.map(([url]) => new URL(String(url), "https://frontend.test").pathname)).toEqual([
      "/api/v1/public/forge/machine-service/uploads", "/api/v1/public/forge/machine-service-requests", "/api/v1/public/machine-service/requests/private-token/status",
    ]);
    expect(fetchMock.mock.calls.slice(0, 2).map(([, init]) => ({ method: init?.method, body: JSON.parse(String(init?.body)) }))).toEqual([
      { method: "POST", body: { machine_type_id: 22, kind: "stl", filename: "part.stl", queue_id: 8, checkin_mid: 443, name: "Ada" } },
      { method: "POST", body: { machine_type_id: 22, title: "Part", queue_id: 8, file_ids: [17], checkin_mid: 443, name: "Ada" } },
    ]);
  });
});
