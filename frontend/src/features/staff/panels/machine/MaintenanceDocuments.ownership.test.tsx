import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MaintenanceDocuments } from "./MaintenanceDocuments";
import { maintenanceKeys } from "./maintenanceApi";
import { maintenanceDocument } from "../../../../test/staffDocumentFixtures";
import {
  chooseFile, cleanUploadSession, contract, held, http, json, login, mountStaff,
  noContent, pdf, release, resetUploadSession, storageUrl, type HttpCall,
} from "../../../../test/staffUploadHarness";

beforeEach(() => { resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => { cleanUploadSession(); });
const props = { machineId: 1, logId: 11, documents: [maintenanceDocument], canDelete: true, retired: false };
function respond(call: HttpCall) {
  if (call.path === storageUrl) return noContent();
  if (call.path.endsWith("presign/")) return json(contract());
  if (call.path.endsWith("url/")) return json({ url: "https://private.test/current" });
  return json(maintenanceDocument);
}

it("owns pending across raw bytes, blocks duplicate/file edits, and retries only finalization with the same key", async () => {
  const raw = held<Response>();
  let finalizations = 0;
  const net = http((call) => {
    if (call.path === storageUrl) return raw.promise;
    if (call.path === "/admin/maintenance/logs/11/documents/" && ++finalizations === 1) return json({ detail: "Transient finalizer failure" }, 503);
    return respond(call);
  });
  const view = mountStaff(<MaintenanceDocuments {...props} />);
  const invalidation = vi.spyOn(view.client, "invalidateQueries");
  chooseFile("Add supporting document");
  const upload = screen.getByRole("button", { name: "Upload" });
  act(() => { fireEvent.click(upload); chooseFile("Add supporting document", new File(["other"], "other.pdf")); fireEvent.click(upload); });
  await waitFor(() => expect(net.calls.filter((call) => call.path === storageUrl)).toHaveLength(1));
  expect(screen.getByLabelText("Add supporting document")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
  expect(net.calls.find((call) => call.path.endsWith("presign/"))?.body.filename).toBe(pdf.name);
  await release(raw, noContent());
  const retry = await screen.findByRole("button", { name: "Retry finalize" });
  await waitFor(() => expect(retry).toBeEnabled());
  expect(await screen.findByText("Transient finalizer failure")).toBeVisible();
  act(() => { fireEvent.click(retry); fireEvent.click(retry); });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry finalize" })).not.toBeInTheDocument());
  expect(net.calls.filter((call) => call.path.endsWith("presign/"))).toHaveLength(1);
  expect(net.calls.filter((call) => call.path === storageUrl)).toHaveLength(1);
  expect(net.calls.filter((call) => call.path === "/admin/maintenance/logs/11/documents/").map((call) => call.body)).toEqual([
    { object_key: "staging/file" }, { object_key: "staging/file" },
  ]);
  expect(invalidation).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logs(1) });
  expect(invalidation).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logDocuments(11) });
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
});

it.each(["resource", "session", "visit"])("a transient receipt key cannot be adopted after %s change", async (change) => {
  let fail = true;
  const net = http((call) => call.path === "/admin/maintenance/logs/11/documents/" && fail
    ? json({ detail: "Try finalization again" }, 503) : respond(call));
  const view = mountStaff(<MaintenanceDocuments {...props} />);
  chooseFile("Add supporting document");
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await screen.findByRole("button", { name: "Retry finalize" });
  if (change === "session") { login("B"); view.rerender(<MaintenanceDocuments {...props} />); }
  else {
    view.rerender(<MaintenanceDocuments {...props} machineId={2} logId={22} />);
    if (change === "visit") view.rerender(<MaintenanceDocuments {...props} />);
  }
  expect(screen.queryByRole("button", { name: "Retry finalize" })).not.toBeInTheDocument();
  expect(screen.queryByText("Try finalization again")).not.toBeInTheDocument();
  expect(net.calls.filter((call) => call.path === "/admin/maintenance/logs/11/documents/")).toHaveLength(1);
  fail = false;
  chooseFile("Add supporting document");
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(net.calls.filter((call) => call.path.endsWith("presign/"))).toHaveLength(2));
  await waitFor(() => expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled());
});

it.each(["actor", "resource"])("held bytes cannot dispatch finalization after %s departure", async (change) => {
  const raw = held<Response>();
  const net = http((call) => call.path === storageUrl ? raw.promise : respond(call));
  const view = mountStaff(<MaintenanceDocuments {...props} />);
  chooseFile("Add supporting document");
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(net.calls.some((call) => call.path === storageUrl)).toBe(true));
  if (change === "actor") login("B");
  view.rerender(<MaintenanceDocuments {...props} machineId={change === "actor" ? 1 : 2} logId={change === "actor" ? 11 : 22} />);
  chooseFile("Add supporting document", new File(["B"], "B.pdf"));
  await release(raw, noContent());
  expect(net.calls.filter((call) => /\/logs\/\d+\/documents\/$/.test(call.path))).toHaveLength(0);
  expect(screen.queryByText("Attachment uploaded")).not.toBeInTheDocument();
  expect((screen.getByLabelText("Add supporting document") as HTMLInputElement).files?.[0]?.name).toBe("B.pdf");
  expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
});

it("resource departure during a held presign cannot start storage or install a retry key", async () => {
  const presign = held<Response>();
  const net = http((call) => call.path.endsWith("presign/") ? presign.promise : respond(call));
  const view = mountStaff(<MaintenanceDocuments {...props} />);
  chooseFile("Add supporting document");
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(net.calls.some((call) => call.path.endsWith("presign/"))).toBe(true));
  view.rerender(<MaintenanceDocuments {...props} machineId={2} logId={22} />);
  await release(presign, json(contract()));
  expect(net.calls.some((call) => call.path === storageUrl)).toBe(false);
  expect(screen.queryByRole("button", { name: "Retry finalize" })).not.toBeInTheDocument();
  expect(screen.queryByText("Attachment uploaded")).not.toBeInTheDocument();
});

it("current download and confirmed deletion keep actual IDs and invalidation", async () => {
  const net = http(respond);
  const view = mountStaff(<MaintenanceDocuments {...props} />);
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() => expect(window.open).toHaveBeenCalledWith("https://private.test/current", "_blank", "noopener,noreferrer"));
  fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete attachment" }));
  await waitFor(() => expect(net.calls.some((call) => call.path === "/admin/maintenance/log-documents/81/" && call.method === "DELETE")).toBe(true));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logs(1) }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logDocuments(11) });
});
