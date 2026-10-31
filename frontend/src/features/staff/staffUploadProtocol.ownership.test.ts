import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import { admitUpload } from "../../lib/uploadProtocol";
import { staffRequest } from "../../lib/api";
import { uploadPublicImage as compatibilityExport } from "./ImageUploader";
import { uploadPublicImage } from "./imageUploadApi";
import { uploadMachineDocument } from "./machineDocumentsApi";
import { uploadWarrantyDocument } from "./warrantyApi";
import {
  assertStorage, cleanUploadSession, contract, held, http, imageContract, json, login,
  noContent, pdf, photo, resetUploadSession, staffToken, storageUrl,
} from "../../test/staffUploadHarness";

beforeEach(() => { resetUploadSession(); });
afterEach(() => { cleanUploadSession(); });

const pipelines = [
  { name: "image", file: photo, presign: "/admin/inventory/17/image", final: "/admin/inventory/17/image", method: "PUT",
    run: (guard = admitUpload()) => uploadPublicImage("/admin/inventory/17/image", photo, { project_id: 8 }, guard),
    metadata: { object_key: "staging/image", project_id: 8 } },
  { name: "machine", file: pdf, presign: "/admin/machines/17/documents/presign", final: "/admin/machines/17/documents", method: "POST",
    run: (guard = admitUpload()) => uploadMachineDocument(17, pdf, "sop", guard),
    metadata: { object_key: "staging/file", doc_type: "sop", original_filename: "manual.pdf" } },
  { name: "warranty", file: pdf, presign: "/admin/warranty/17/documents/presign", final: "/admin/warranty/17/documents", method: "POST",
    run: (guard = admitUpload()) => uploadWarrantyDocument(17, pdf, guard),
    metadata: { object_key: "staging/file", original_filename: "manual.pdf" } },
];

describe.each(pipelines)("$name admitted upload transport", (pipeline) => {
  it.each(["PUT", "POST"])("preserves current %s storage, MIME, file metadata and application bearer", async (method) => {
    const net = http((call) => {
      if (call.path === "/config") return json({ public_image_max_bytes: 1024 });
      if (call.path === storageUrl) return noContent();
      if (call.path === pipeline.presign && call.method === "POST") return json(pipeline.name === "image" ? imageContract(method) : contract(method));
      return json({ id: 88 });
    });
    await pipeline.run();
    const presign = net.calls.find((call) => call.path === pipeline.presign && call.method === "POST")!;
    expect(presign.body).toEqual({ filename: pipeline.file.name, content_type: pipeline.file.type, ...(pipeline.name === "image" ? { project_id: 8 } : {}) });
    expect(new Headers(presign.init.headers).get("Authorization")).toBe(`Bearer ${staffToken()}`);
    const bytes = net.calls.find((call) => call.path === storageUrl)!;
    // Image's descriptor uses its own key; inspect the shared mechanics with that descriptor too.
    assertStorage(bytes, pipeline.file, method);
    const final = net.calls.find((call) => call.path === pipeline.final && call.method === pipeline.method)!;
    expect(final.body).toEqual(pipeline.metadata);
    expect(new Headers(final.init.headers).get("Authorization")).toBe(`Bearer ${staffToken()}`);
    expect(compatibilityExport).toBe(uploadPublicImage);
  });

  it("invalidates a held presign before any raw dispatch", async () => {
    const presign = held<Response>();
    const net = http((call) => call.path === "/config" ? json({ public_image_max_bytes: 1024 }) : presign.promise);
    let current = true;
    const result = pipeline.run(admitUpload(() => current)).then(() => "published", () => "obsolete");
    // Wait for actual presign admission, rather than invalidating before the first await.
    await waitFor(() => expect(net.calls.some((c) => c.path === pipeline.presign)).toBe(true));
    current = false;
    presign.resolve(json(pipeline.name === "image" ? imageContract() : contract()));
    expect(await result).toBe("obsolete");
    expect(net.calls.some((c) => c.path === storageUrl)).toBe(false);
    expect(net.calls.filter((c) => c.method === pipeline.method && c.path === pipeline.final)).toHaveLength(0);
  });

  it("cannot attach after an actor switch during already-dispatched raw bytes", async () => {
    const bytes = held<Response>();
    const net = http((call) => {
      if (call.path === "/config") return json({ public_image_max_bytes: 1024 });
      return call.path === storageUrl ? bytes.promise : json(pipeline.name === "image" ? imageContract() : contract());
    });
    const result = pipeline.run().then(() => "published", () => "obsolete");
    await waitFor(() => expect(net.calls.some((c) => c.path === storageUrl)).toBe(true));
    login("B");
    bytes.resolve(noContent());
    expect(await result).toBe("obsolete");
    expect(net.calls.filter((c) => c.path === pipeline.final && c.method === pipeline.method)).toHaveLength(0);
    // A meaningful current control proves B is authorized by the real transport.
    await staffRequest("/control-current-B");
    expect(new Headers(net.calls[net.calls.length - 1].init.headers).get("Authorization")).toBe(`Bearer ${staffToken("B")}`);
  });

  it("does not publish an already-dispatched finalizer into a different resource visit", async () => {
    const final = held<Response>();
    let current = true;
    const net = http((call) => {
      if (call.path === "/config") return json({ public_image_max_bytes: 1024 });
      if (call.path === storageUrl) return noContent();
      if (call.method === pipeline.method && call.path === pipeline.final) return final.promise;
      return json(pipeline.name === "image" ? imageContract() : contract());
    });
    const result = pipeline.run(admitUpload(() => current)).then(() => "published", () => "obsolete");
    await waitFor(() => expect(net.calls.some((c) => c.path === pipeline.final && c.method === pipeline.method)).toBe(true));
    current = false;
    final.resolve(json({ id: 88 }));
    expect(await result).toBe("obsolete");
  });
});
