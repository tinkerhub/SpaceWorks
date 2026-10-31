import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { WarrantySection } from "./WarrantySection";
import type { Warranty } from "./warrantyApi";
import { cleanUploadSession, held, http, json, mountStaff, release, resetUploadSession } from "../../test/staffUploadHarness";
import { warrantyFixture } from "../../test/staffDocumentFixtures";
beforeEach(() => { resetUploadSession(); });
afterEach(() => { cleanUploadSession(); });

it("holds every metadata field and prevents upsert PUT until the initial GET hydrates existing data", async () => {
  const get = held<Response>();
  const net = http((call) => call.method === "GET" ? get.promise : json(warrantyFixture()));
  mountStaff(<WarrantySection hostKind="machine" hostId={1} />);
  await waitFor(() => expect(net.calls).toHaveLength(1));
  for (const label of ["Purchased", "Expires", "Vendor", "Contact"]) expect(screen.getByLabelText(label)).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Vendor"), { target: { value: "premature" } });
  fireEvent.click(screen.getByRole("button", { name: "Create warranty" }));
  expect(net.calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  await release(get, json(warrantyFixture()));
  await waitFor(() => expect(screen.getByLabelText("Vendor")).toHaveValue("Existing vendor"));
  expect(screen.getByLabelText("Contact")).toHaveValue("Private existing contact");
  expect(screen.getByLabelText("Purchased")).toHaveValue("2026-01-02");
  expect(screen.getByLabelText("Expires")).toHaveValue("2027-01-02");
  expect(screen.getByRole("button", { name: "Save warranty" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Save warranty" }));
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(net.writes()[0]).toMatchObject({ path: "/admin/machines/1/warranty", method: "PUT", body: {
    purchased_on: "2026-01-02", warranty_expires_on: "2027-01-02", vendor_name: "Existing vendor", vendor_contact: "Private existing contact",
  } });
});

it.each(["null", "existing"])("initial error stays disabled until explicit retry resolves %s data", async (data) => {
  let reads = 0;
  const net = http((call) => {
    if (call.method === "GET") return ++reads === 1 ? json({ detail: "Warranty unavailable" }, 503) : json(data === "null" ? null : warrantyFixture());
    return json(warrantyFixture());
  });
  mountStaff(<WarrantySection hostKind="machine" hostId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: "Create warranty" }));
  const retry = await screen.findByRole("button", { name: "Retry" });
  expect(screen.getByLabelText("Vendor")).toBeDisabled();
  expect(net.writes()).toHaveLength(0);
  fireEvent.click(retry);
  const save = await screen.findByRole("button", { name: data === "null" ? "Create warranty" : "Save warranty" });
  await waitFor(() => expect(save).toBeEnabled());
  expect(screen.getByLabelText("Vendor")).toHaveValue(data === "null" ? "" : "Existing vendor");
  fireEvent.click(save);
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(net.writes()[0].body.vendor_name).toBe(data === "null" ? "" : "Existing vendor");
  expect(reads).toBe(2);
});

it("preserves dirty same-visit metadata across document refresh and background refetch, then hydrates its own normalized save", async () => {
  let dto = warrantyFixture();
  const net = http((call) => json(call.method === "PUT" ? { ...dto, vendor_name: "Normalized vendor", vendor_contact: "Normalized contact" } : dto));
  const view = mountStaff(<WarrantySection hostKind="machine" hostId={1} />);
  await waitFor(() => expect(screen.getByLabelText("Vendor")).toHaveValue("Existing vendor"));
  fireEvent.change(screen.getByLabelText("Vendor"), { target: { value: "  Dirty vendor  " } });
  fireEvent.change(screen.getByLabelText("Contact"), { target: { value: " Dirty contact " } });
  dto = { ...dto, documents: [{ id: 91, original_filename: "new.pdf", content_type: "application/pdf", size_bytes: 4, created_at: "2026-01-02" }] };
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["warranty", "machine", 1] }); });
  expect(await screen.findByText("new.pdf")).toBeVisible();
  expect(screen.getByLabelText("Vendor")).toHaveValue("  Dirty vendor  ");
  dto = { ...dto, vendor_name: "External refetch", vendor_contact: "External contact",
    documents: dto.documents.map((document) => ({ ...document, original_filename: "external.pdf" })) };
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["warranty", "machine", 1] }); });
  await screen.findByText("external.pdf"); // Observe the actual component render, not just the cache write.
  await waitFor(() => expect(view.client.getQueryData<Warranty>(["warranty", "machine", 1])?.vendor_name).toBe("External refetch"));
  expect(screen.getByLabelText("Contact")).toHaveValue(" Dirty contact ");
  fireEvent.click(screen.getByRole("button", { name: "Save warranty" }));
  await waitFor(() => expect(screen.getByLabelText("Vendor")).toHaveValue("Normalized vendor"));
  expect(screen.getByLabelText("Contact")).toHaveValue("Normalized contact");
  expect(net.writes()[0].body).toMatchObject({ vendor_name: "Dirty vendor", vendor_contact: "Dirty contact" });
});

it.each(["host", "kind"])("%s change resets private fields and obsolete save cannot hydrate the new editor", async (change) => {
  const save = held<Response>();
  const newGet = held<Response>();
  const net = http((call) => call.method === "PUT" ? save.promise
    : call.path === "/admin/machines/1/warranty" ? json(warrantyFixture()) : newGet.promise);
  const view = mountStaff(<WarrantySection hostKind="machine" hostId={1} />);
  await waitFor(() => expect(screen.getByLabelText("Vendor")).toHaveValue("Existing vendor"));
  fireEvent.change(screen.getByLabelText("Vendor"), { target: { value: "Private A edit" } });
  fireEvent.click(screen.getByRole("button", { name: "Save warranty" }));
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  view.rerender(<WarrantySection hostKind={change === "kind" ? "asset" : "machine"} hostId={change === "kind" ? 1 : 2} />);
  expect(screen.getByLabelText("Vendor")).toHaveValue("");
  expect(screen.getByLabelText("Contact")).toHaveValue("");
  expect(screen.getByLabelText("Vendor")).toBeDisabled();
  await release(save, json({ ...warrantyFixture(), vendor_name: "Late saved A" }));
  expect(screen.queryByText("Warranty saved.")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Vendor")).toHaveValue("");
  await release(newGet, json(null));
  await waitFor(() => expect(screen.getByLabelText("Vendor")).toBeEnabled());
});
