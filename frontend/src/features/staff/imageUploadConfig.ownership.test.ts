import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { held, http, imageContract, json, noContent, photo, staffToken, storageUrl } from "../../test/staffUploadHarness";

// Reset only this protocol suite's module registry: each case needs a cold config cache.
let session: typeof import("../../lib/apiSession");
let upload: typeof import("./imageUploadApi").uploadPublicImage;
beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
  session = await import("../../lib/apiSession");
  session.setAccessToken(staffToken());
  upload = (await import("./imageUploadApi")).uploadPublicImage;
});
afterEach(() => {
  session.clearAccessToken();
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(["network", "zero", "invalid"])("retries explicit upload after %s config failure without a poisoned promise", async (failure) => {
  let configReads = 0;
  const net = http((call) => {
    if (call.path === "/config") {
      configReads++;
      if (configReads === 1) {
        if (failure === "network") return Promise.reject(new TypeError("offline"));
        return json({ public_image_max_bytes: failure === "zero" ? 0 : "invalid" });
      }
      return json({ public_image_max_bytes: 1024 });
    }
    if (call.path === storageUrl) return noContent();
    return call.method === "POST" ? json(imageContract()) : json({});
  });
  await expect(upload("/admin/items/2/image", photo)).rejects.toThrow();
  expect(net.writes()).toHaveLength(0);
  await expect(upload("/admin/items/2/image", photo)).resolves.toBeUndefined();
  expect(configReads).toBe(2);
  await upload("/admin/items/2/image", photo);
  expect(configReads).toBe(2); // Only a valid successful cap remains cached.
  expect(net.writes().map((call) => call.method)).toEqual(["POST", "PUT", "POST", "PUT"]);
});

it("accepts the exact cap, rejects oversize before presign, and snapshots extra body", async () => {
  const gate = held<Response>();
  const net = http((call) => call.path === "/config" ? gate.promise
    : call.path === storageUrl ? noContent() : json(call.method === "POST" ? imageContract() : {}));
  const extra = { project_id: 7, crop: { x: 1 } };
  const result = upload("/admin/profile/image", photo, extra);
  await waitFor(() => expect(net.calls[0]?.path).toBe("/config"));
  extra.project_id = 9;
  extra.crop.x = 2;
  gate.resolve(json({ public_image_max_bytes: photo.size }));
  await result;
  expect(net.writes().map((call) => call.body)).toEqual([
    { filename: photo.name, content_type: photo.type, project_id: 7, crop: { x: 1 } },
    { object_key: "staging/image", project_id: 7, crop: { x: 1 } },
  ]);
  await expect(upload("/admin/profile/image", new File(["x".repeat(photo.size + 1)], "too.png"))).rejects.toThrow("Image too large");
  expect(net.writes()).toHaveLength(2);
});

it("captures admission before config and blocks presign after an epoch change", async () => {
  const config = held<Response>();
  const net = http(() => config.promise);
  const outcome = upload("/admin/items/1/image", photo).then(() => "published", () => "obsolete");
  await waitFor(() => expect(net.calls[0]?.path).toBe("/config"));
  session.setAccessToken(staffToken("B"));
  config.resolve(json({ public_image_max_bytes: 1024 }));
  expect(await outcome).toBe("obsolete");
  expect(net.writes()).toHaveLength(0);
});
