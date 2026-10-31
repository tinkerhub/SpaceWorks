import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WarrantySection } from "./WarrantySection";
import { ProcurementReceipts } from "./panels/ProcurementReceipts";
import { warrantyFixture } from "../../test/staffDocumentFixtures";
import {
  cleanUploadSession, contract, held, http, json, login, mountStaff, noContent, pdf,
  release, resetUploadSession, selectFiles, storageUrl, type HttpCall,
} from "../../test/staffUploadHarness";

beforeEach(() => { resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => { cleanUploadSession(); });
const secondFile = new File(["%PDF-second"], "second.pdf", { type: "application/pdf" });
const receipt = { id: 81, created_at: "2026-01-02", uploaded_by: 1, uploaded_by_username: "A" };
const document = { id: 81, original_filename: "existing.pdf", content_type: "application/pdf", size_bytes: 8, created_at: "2026-01-02" };
const surfaces = [
  { name: "warranty", presign: "/admin/warranty/41/documents/presign", final: "/admin/warranty/41/documents",
    view: "/admin/warranty/documents/81/url", remove: "/admin/warranty/documents/81", confirm: "Remove document", removeButton: "Remove…",
    ui: (id: number, _changed: () => void) => <WarrantySection hostKind="machine" hostId={id} /> },
  { name: "receipt", presign: "/procurement/to-buy/1/receipts/presign", final: "/procurement/to-buy/1/receipts",
    view: "/procurement/to-buy/receipts/81/url", remove: "/procurement/to-buy/receipts/81", confirm: "Delete receipt", removeButton: "Delete…",
    ui: (id: number, changed: () => void) => <ProcurementReceipts itemId={id} receipts={[receipt]} onChanged={changed} /> },
];
function responder(call: HttpCall) {
  if (call.path === storageUrl) return noContent();
  if (call.path.endsWith("/warranty")) return json({ ...warrantyFixture(Number(call.path.split("/")[3])), documents: [document] });
  if (call.path.endsWith("/presign")) return json(contract());
  if (call.path.endsWith("/url")) return json({ url: "https://private.test/current" });
  return json({ id: 81 });
}

describe.each(surfaces)("$name captured document batch", (surface) => {
  it("captures files and target, refreshes partial current success and permits retry", async () => {
    let presigns = 0;
    let failure = true;
    const changed = vi.fn();
    const net = http((call) => call.path.endsWith("/presign") && ++presigns === 2 && failure
      ? json({ detail: "Second file unavailable" }, 503) : responder(call));
    const view = mountStaff(surface.ui(1, changed));
    if (surface.name === "warranty") await screen.findByText("existing.pdf");
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    const batch = [pdf, secondFile];
    selectFiles(view.container, batch);
    batch.reverse(); // The admitted browser FileList has already been copied.
    await screen.findAllByText("Second file unavailable");
    expect(net.calls.filter((call) => call.path === surface.presign).map((call) => call.body.filename)).toEqual(["manual.pdf", "second.pdf"]);
    expect(net.calls.filter((call) => call.path === surface.final)).toHaveLength(1);
    if (surface.name === "receipt") expect(changed).toHaveBeenCalledTimes(1);
    else await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["warranty", "machine", 1] }));
    failure = false;
    selectFiles(view.container, [secondFile]);
    await waitFor(() => expect(net.calls.filter((call) => call.path === surface.final)).toHaveLength(2));
    if (surface.name === "receipt") await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
    expect(net.calls.find((call) => call.path === surface.final)?.body).toEqual({ object_key: "staging/file", ...(surface.name === "warranty" ? { original_filename: "manual.pdf" } : {}) });
  });

  it.each(["success", "error"])("late A raw %s cannot clear or unlock B, toast, refresh B or continue A's batch", async (outcome) => {
    const rawA = held<Response>(); const rawB = held<Response>();
    let bytes = 0;
    const changedA = vi.fn(); const changedB = vi.fn();
    const net = http((call) => call.path === storageUrl ? (++bytes === 1 ? rawA.promise : rawB.promise) : responder(call));
    const view = mountStaff(surface.ui(1, changedA));
    if (surface.name === "warranty") await screen.findByText("existing.pdf");
    selectFiles(view.container, [pdf, secondFile]);
    await waitFor(() => expect(bytes).toBe(1));
    view.rerender(surface.ui(2, changedB));
    if (surface.name === "warranty") await waitFor(() => expect(screen.getByLabelText("Vendor")).toBeEnabled());
    const inputB = selectFiles(view.container, [secondFile]);
    await waitFor(() => expect(bytes).toBe(2));
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    await release(rawA, outcome === "success" ? noContent() : new Response(null, { status: 503 }));
    expect(inputB).toBeDisabled();
    expect(changedA).not.toHaveBeenCalled(); expect(changedB).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
    expect(net.calls.filter((call) => call.path === surface.presign)).toHaveLength(1);
    expect(net.calls.filter((call) => call.path === surface.final)).toHaveLength(0);
    expect(screen.queryByText(/Storage upload failed/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Receipt added\.|Document attached\./)).not.toBeInTheDocument();
    await release(rawB, noContent());
    await waitFor(() => expect(inputB).toBeEnabled());
    const target = surface.name === "receipt" ? "/procurement/to-buy/2/receipts" : "/admin/warranty/42/documents";
    expect(net.calls.find((call) => call.path === target)?.body).toMatchObject({ object_key: "staging/file" });
  });

  it("does not recapture a new actor between files after a held first finalizer", async () => {
    const final = held<Response>();
    const changed = vi.fn();
    const net = http((call) => call.path === surface.final ? final.promise : responder(call));
    const view = mountStaff(surface.ui(1, changed));
    if (surface.name === "warranty") await screen.findByText("existing.pdf");
    selectFiles(view.container, [pdf, secondFile]);
    await waitFor(() => expect(net.calls.some((call) => call.path === surface.final)).toBe(true));
    login("B");
    view.rerender(surface.ui(1, changed));
    await release(final, json({ id: 81 }));
    expect(net.calls.filter((call) => call.path === surface.presign)).toHaveLength(1);
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText(/documents attached|receipts added/)).not.toBeInTheDocument();
  });

  it("current view and delete use the actual document/receipt ID", async () => {
    const changed = vi.fn();
    const net = http(responder);
    const view = mountStaff(surface.ui(1, changed));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await waitFor(() => expect(window.open).toHaveBeenCalledWith("https://private.test/current", "_blank", "noopener"));
    expect(net.calls.some((call) => call.path === surface.view)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: surface.removeButton }));
    fireEvent.click(await screen.findByRole("button", { name: surface.confirm }));
    await waitFor(() => expect(net.calls.some((call) => call.path === surface.remove && call.method === "DELETE")).toBe(true));
    if (surface.name === "receipt") await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    else await waitFor(() => expect(view.client.getQueryState(["warranty", "machine", 1])?.fetchStatus).toBe("idle"));
  });

  it("private view completion after unmount cannot open a tab", async () => {
    const url = held<Response>();
    const net = http((call) => call.path === surface.view ? url.promise : responder(call));
    const view = mountStaff(surface.ui(1, vi.fn()));
    fireEvent.click(await screen.findByRole("button", { name: "View" }));
    await waitFor(() => expect(net.calls.some((call) => call.path === surface.view)).toBe(true));
    view.unmount();
    await release(url, json({ url: "https://private.test/obsolete" }));
    expect(window.open).not.toHaveBeenCalled();
  });

  it("a held presign invalidated by resource change never dispatches raw bytes", async () => {
    const presign = held<Response>();
    const changed = vi.fn();
    const net = http((call) => call.path === surface.presign ? presign.promise : responder(call));
    const view = mountStaff(surface.ui(1, changed));
    if (surface.name === "warranty") await screen.findByText("existing.pdf");
    selectFiles(view.container, [pdf, secondFile]);
    await waitFor(() => expect(net.calls.some((call) => call.path === surface.presign)).toBe(true));
    view.rerender(surface.ui(2, changed));
    await release(presign, json(contract()));
    expect(net.calls.some((call) => call.path === storageUrl)).toBe(false);
    expect(changed).not.toHaveBeenCalled();
  });

  it("obsolete deletion cannot dismiss B's confirmation or refresh/toast B", async () => {
    const remove = held<Response>();
    const changedA = vi.fn(); const changedB = vi.fn();
    const net = http((call) => call.method === "DELETE" ? remove.promise : responder(call));
    const view = mountStaff(surface.ui(1, changedA));
    fireEvent.click(await screen.findByRole("button", { name: surface.removeButton }));
    fireEvent.click(await screen.findByRole("button", { name: surface.confirm }));
    await waitFor(() => expect(net.calls.some((call) => call.method === "DELETE")).toBe(true));
    view.rerender(surface.ui(2, changedB));
    fireEvent.click(await screen.findByRole("button", { name: surface.removeButton }));
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    await release(remove, json({}));
    expect(screen.getByRole("button", { name: surface.confirm })).toBeEnabled();
    expect(changedA).not.toHaveBeenCalled(); expect(changedB).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
    expect(screen.queryByText(/Receipt deleted\.|Document removed\./)).not.toBeInTheDocument();
  });
});
