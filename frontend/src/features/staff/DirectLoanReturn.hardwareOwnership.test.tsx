import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DirectLoans } from "./DirectLoans";
import {
  field, dialog, endHardwareTest, hardwareHttp, held, json, loanA, login, maker, mountHardware,
  paused, release, resume, scanner, setValue, startHardwareTest, uploadPhoto,
} from "../../test/hardwareOwnershipHarness";
import type { HttpCall } from "../../test/staffUploadHarness";

vi.mock("../../components/ui/QrScanner", async () => {
  const { ScannerLeaf } = await import("../../test/hardwareOwnershipHarness");
  return { default: ScannerLeaf };
});
beforeEach(startHardwareTest);
afterEach(endHardwareTest);
const returns = (calls: HttpCall[]) => calls.filter((call) => call.path.endsWith("/return"));
function openReturn(label = "Scope loan A") {
  fireEvent.click(within(screen.getByText(label).closest("tr")!).getByRole("button", { name: "Return" }));
}
async function fillReturn() {
  await uploadPhoto("Return photo");
  setValue("Return notes", "One unit damaged, meter missing");
  setValue("Return QR scan", "BOX-RETURN-A");
  setValue("Returned", "1");
  setValue("Damaged", "1");
  setValue("UNIT-61", "missing");
}

it("current direct return requires photo/notes/scan/all outcomes and freezes its complete DTO before a pause", async () => {
  const net = hardwareHttp();
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await screen.findByText("Scope loan A");
  openReturn();
  const submit = dialog().getByRole("button", { name: "Submit return" });
  expect(submit).toBeDisabled();
  await uploadPhoto("Return photo");
  expect(submit).toBeDisabled();
  setValue("Return notes", "One unit damaged, meter missing");
  expect(submit).toBeDisabled();
  setValue("Return QR scan", "BOX-RETURN-A");
  setValue("Returned", "1");
  expect(submit).toBeDisabled();
  setValue("Damaged", "1");
  setValue("UNIT-61", "missing");
  expect(submit).toBeEnabled();
  fireEvent.click(dialog().getByRole("button", { name: "Scan QR" }));
  const native = scanner.current!;
  onlineManager.setOnline(false);
  const form = document.getElementById("direct-loan-return-form")!;
  act(() => {
    fireEvent.submit(form);
    setValue("Return notes", "Later note");
    setValue("Return QR scan", "LATER-CODE");
    setValue("Damaged", "0");
    setValue("UNIT-61", "returned");
    void native.onScan("LATE-NATIVE");
    fireEvent.submit(form);
  });
  await paused(view.client);
  expect(returns(net.calls)).toHaveLength(0);
  expect(field("Return notes")).toHaveValue("One unit damaged, meter missing");
  expect(field("UNIT-61")).toHaveValue("missing");
  await resume(view.client);
  await screen.findByText("Return recorded.");
  expect(returns(net.calls)).toHaveLength(1);
  expect(returns(net.calls)[0]).toMatchObject({ path: "/admin/direct-loans/81/return", body: {
    evidence_id: 71, notes: "One unit damaged, meter missing", qr_payload: "BOX-RETURN-A",
    resolutions: [{ item_id: 91, returned: 1, damaged: 1, missing: 0 },
      { item_id: 92, returned: 0, damaged: 0, missing: 1, assets: [{ asset_id: 61, outcome: "missing" }] }],
  } });
});

it.each(["actor", "unmount"])("paused return does not dispatch after %s departure", async (departure) => {
  const net = hardwareHttp();
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await screen.findByText("Scope loan A");
  openReturn();
  await fillReturn();
  onlineManager.setOnline(false);
  fireEvent.submit(document.getElementById("direct-loan-return-form")!);
  await paused(view.client);
  if (departure === "actor") login("B");
  view.rerender(departure === "unmount" ? <p>Left returns</p> : <DirectLoans makerspace={maker} />);
  await resume(view.client);
  expect(returns(net.calls)).toHaveLength(0);
  expect(screen.queryByText(/Return recorded\.|Handout visit changed/)).not.toBeInTheDocument();
});

it.each(["success", "error"])("old return %s/finally cannot close or unlock B's return dialog", async (outcome) => {
  const responseA = held<Response>(); const responseB = held<Response>(); let count = 0;
  const net = hardwareHttp((call) => call.path.endsWith("/return") ? ++count === 1 ? responseA.promise : responseB.promise : undefined);
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await screen.findByText("Scope loan A");
  openReturn();
  await fillReturn();
  fireEvent.submit(document.getElementById("direct-loan-return-form")!);
  await waitFor(() => expect(count).toBe(1));
  login("B");
  view.rerender(<DirectLoans makerspace={maker} />);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await screen.findByText("Scope loan B");
  openReturn("Scope loan B");
  await fillReturn();
  setValue("Return notes", "B return draft");
  fireEvent.submit(document.getElementById("direct-loan-return-form")!);
  await waitFor(() => expect(count).toBe(2));
  await release(responseA, outcome === "success" ? json({ id: 81 }) : json({ detail: "Old return error" }, 409));
  expect(screen.getByRole("heading", { name: "Return Scope loan B" })).toBeVisible();
  expect(field("Return notes")).toHaveValue("B return draft");
  expect(field("Return notes")).toBeDisabled();
  expect(screen.queryByText(/Return recorded\.|Old return error/)).not.toBeInTheDocument();
  expect(returns(net.calls)).toHaveLength(2);
  await release(responseB, json({ id: 82 }));
  await screen.findByText("Return recorded.");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("retained closed native return callback cannot write into a new loan visit", async () => {
  hardwareHttp();
  mountHardware(<DirectLoans makerspace={maker} />);
  await screen.findByText("Scope loan A");
  openReturn();
  fireEvent.click(dialog().getByRole("button", { name: "Scan QR" }));
  const old = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Close native scanner" }));
  fireEvent.click(dialog().getByRole("button", { name: "Cancel" }));
  openReturn("Scope loan B");
  setValue("Return QR scan", "B-CURRENT");
  await act(async () => { await old.onScan("OLD-A"); });
  expect(field(/^Return QR scan/)).toHaveValue("B-CURRENT");
});

it("a current return marked scan-optional remains photo/notes-required and submits without a QR", async () => {
  const net = hardwareHttp(undefined, [], [{ ...loanA, return_scan_required: false, return_items: loanA.return_items?.slice(0, 1) }]);
  mountHardware(<DirectLoans makerspace={maker} />);
  await screen.findByText("Scope loan A");
  openReturn();
  await uploadPhoto("Return photo");
  expect(dialog().getByRole("button", { name: "Submit return" })).toBeDisabled();
  setValue("Return notes", "All units intact");
  fireEvent.submit(document.getElementById("direct-loan-return-form")!);
  await screen.findByText("Return recorded.");
  expect(returns(net.calls)[0].body).toEqual({ evidence_id: 71, notes: "All units intact", qr_payload: "",
    resolutions: [{ item_id: 91, returned: 2, damaged: 0, missing: 0 }] });
});
