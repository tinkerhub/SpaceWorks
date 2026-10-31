import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DocumentsTab } from "./DocumentsTab";
import { machineKeys } from "../../machinesApi";
import { machineDocument } from "../../../../test/staffDocumentFixtures";
import {
  chooseFile, cleanUploadSession, contract, held, http, json, login, mountStaff,
  noContent, pdf, release, resetUploadSession, storageUrl,
} from "../../../../test/staffUploadHarness";

beforeEach(() => { resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => { cleanUploadSession(); });
function readOrUpload(call: { path: string; method: string }) {
  if (call.path === storageUrl) return noContent();
  if (call.path.endsWith("/presign")) return json(contract());
  if (call.path.endsWith("/url")) return json({ url: "https://private.test/current" });
  if (call.method === "GET") return json({ count: 1, results: [machineDocument] });
  return json(machineDocument);
}
function selectSop() {
  fireEvent.click(screen.getByRole("combobox", { name: "Document type" }));
  fireEvent.click(screen.getByRole("option", { name: "SOP" }));
}
function submitUpload() {
  const file = screen.getByLabelText("File") as HTMLInputElement;
  expect(file).toBeRequired();
  expect(file.files).toHaveLength(1);
  // fireEvent's FileList does not update jsdom's internal required-file validity.
  // Exercise the real form submit handler after the actual file-change handler.
  fireEvent.submit(screen.getByRole("button", { name: "Upload" }).closest("form")!);
}

it.each(["resource", "actor"])("raw upload cannot finalize under the new %s or clear its selected file/type", async (change) => {
  const raw = held<Response>();
  const net = http((call) => call.path === storageUrl ? raw.promise : readOrUpload(call));
  const view = mountStaff(<DocumentsTab machineId={1} canEdit />);
  await screen.findByText("existing.pdf");
  chooseFile("File"); selectSop();
  submitUpload();
  await waitFor(() => expect(net.calls.some((call) => call.path === storageUrl)).toBe(true));
  if (change === "actor") login("B");
  view.rerender(<DocumentsTab machineId={change === "resource" ? 2 : 1} canEdit />);
  await waitFor(() => expect(screen.getByLabelText("File")).toBeEnabled());
  const next = new File(["%PDF-B"], "B.pdf", { type: "application/pdf" });
  chooseFile("File", next); selectSop();
  await release(raw, noContent());
  expect(net.calls.filter((call) => call.method === "POST" && /\/documents$/.test(call.path))).toHaveLength(0);
  expect((screen.getByLabelText("File") as HTMLInputElement).files?.[0]).toBe(next);
  expect(screen.getByRole("combobox", { name: "Document type" })).toHaveTextContent("SOP");
  expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  expect(screen.queryByText(/Couldn't upload/)).not.toBeInTheDocument();
});

it.each(["resource", "unmount"])("held private URL never opens after %s", async (change) => {
  const url = held<Response>();
  const net = http((call) => call.path.endsWith("/url") ? url.promise : readOrUpload(call));
  const view = mountStaff(<DocumentsTab machineId={1} canEdit />);
  fireEvent.click(await screen.findByRole("button", { name: "View" }));
  await waitFor(() => expect(net.calls.some((call) => call.path === "/admin/machines/documents/81/url")).toBe(true));
  if (change === "unmount") view.unmount();
  else view.rerender(<DocumentsTab machineId={2} canEdit />);
  await release(url, json({ url: "https://private.test/obsolete" }));
  expect(window.open).not.toHaveBeenCalled();
});

it("current upload retries, snapshots type, refreshes documents, views and deletes actual document ID", async () => {
  let fail = true;
  const net = http((call) => call.path === storageUrl && fail ? new Response(null, { status: 503 }) : readOrUpload(call));
  const view = mountStaff(<DocumentsTab machineId={17} canEdit />);
  const invalidation = vi.spyOn(view.client, "invalidateQueries");
  await screen.findByText("existing.pdf");
  chooseFile("File"); selectSop();
  submitUpload();
  await screen.findByText("Storage upload failed (503)");
  fail = false;
  submitUpload();
  await waitFor(() => expect(invalidation).toHaveBeenCalledWith({ queryKey: machineKeys.documents(17) }));
  const final = net.calls.find((call) => call.path === "/admin/machines/17/documents" && call.method === "POST");
  expect(final?.body).toEqual({ object_key: "staging/file", original_filename: pdf.name, doc_type: "sop" });
  fireEvent.click(screen.getByRole("button", { name: "View" }));
  await waitFor(() => expect(window.open).toHaveBeenCalledWith("https://private.test/current", "_blank", "noopener,noreferrer"));
  fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete document" }));
  await waitFor(() => expect(net.calls.some((call) => call.path === "/admin/machines/documents/81" && call.method === "DELETE")).toBe(true));
});

it("stale delete settlement cannot dismiss the new resource's confirmation", async () => {
  const remove = held<Response>();
  const net = http((call) => call.method === "DELETE" ? remove.promise : readOrUpload(call));
  const view = mountStaff(<DocumentsTab machineId={1} canEdit />);
  fireEvent.click(await screen.findByRole("button", { name: "Delete…" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete document" }));
  await waitFor(() => expect(net.calls.some((call) => call.method === "DELETE")).toBe(true));
  view.rerender(<DocumentsTab machineId={2} canEdit />);
  fireEvent.click(await screen.findByRole("button", { name: "Delete…" }));
  await release(remove, json({}));
  expect(screen.getByRole("button", { name: "Delete document" })).toBeEnabled();
  expect(screen.queryByText("existing.pdf deleted")).not.toBeInTheDocument();
});

it("blocks same-tick duplicate submits and type/file edits while raw bytes are pending", async () => {
  const raw = held<Response>();
  const net = http((call) => call.path === storageUrl ? raw.promise : readOrUpload(call));
  mountStaff(<DocumentsTab machineId={1} canEdit />);
  await screen.findByText("existing.pdf");
  chooseFile("File"); selectSop();
  const form = screen.getByRole("button", { name: "Upload" }).closest("form")!;
  act(() => { fireEvent.submit(form); chooseFile("File", new File(["other"], "other.pdf")); fireEvent.submit(form); });
  await waitFor(() => expect(net.calls.filter((call) => call.path.endsWith("/presign"))).toHaveLength(1));
  expect(screen.getByLabelText("File")).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Document type" })).toBeDisabled();
  await release(raw, noContent());
  await waitFor(() => expect(net.calls.find((call) => call.path === "/admin/machines/1/documents" && call.method === "POST")?.body.original_filename).toBe("manual.pdf"));
});
