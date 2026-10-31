import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DirectLoans } from "./DirectLoans";
import {
  field, asset, endHardwareTest, hardwareHttp, held, json, login, maker, mountHardware, paused,
  readyDirect, release, resume, scanner, setValue, startHardwareTest, uploadPhoto, waitForChoice,
} from "../../test/hardwareOwnershipHarness";
import type { HttpCall } from "../../test/staffUploadHarness";

vi.mock("../../components/ui/QrScanner", async () => {
  const { ScannerLeaf } = await import("../../test/hardwareOwnershipHarness");
  return { default: ScannerLeaf };
});
beforeEach(startHardwareTest);
afterEach(endHardwareTest);
const issueCalls = (calls: HttpCall[]) => calls.filter((call) => call.method === "POST" && call.path.endsWith("/direct-loans"));
const issueButton = () => screen.getByRole("button", { name: "Issue direct handout" });

it("paused actual issue captures borrower/items/QR/container/evidence/remark and fences all same-tick edits", async () => {
  const net = hardwareHttp();
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await readyDirect();
  setValue("Container", "31");
  setValue("QR payloads", "PASTED-1\nPASTED-2");
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  await act(async () => { await scanner.current!.onScan("UNIT-1"); });
  await screen.findByRole("list", { name: "Scanned QR codes" });
  const native = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
  setValue("Name", "Blocked walk-in");
  onlineManager.setOnline(false);
  const submit = issueButton();
  act(() => {
    fireEvent.click(submit);
    setValue("Borrowing member", "12");
    setValue("Product", "6");
    setValue("Quantity", "99");
    setValue("Container", "32");
    setValue("QR payloads", "LATER");
    setValue("Issue remark", "Later remark");
    setValue("Name", "Late name");
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
    void native.onScan("LATE-NATIVE");
    fireEvent.click(submit);
  });
  await paused(view.client);
  expect(issueCalls(net.calls)).toHaveLength(0);
  expect(field("Borrowing member")).toHaveValue("11");
  expect(field("Issue remark")).toHaveValue("Click-time handout");
  expect(field("Quantity")).toHaveValue(2);
  expect(field("Name")).toHaveValue("Blocked walk-in");
  expect(net.calls.some((call) => call.path.endsWith("/walk-in-members"))).toBe(false);
  expect(net.calls.some((call) => call.body.payload === "LATE-NATIVE")).toBe(false);
  await resume(view.client);
  await screen.findByText("Handout issued.");
  expect(issueCalls(net.calls)).toHaveLength(1);
  expect(issueCalls(net.calls)[0].body).toEqual({
    borrower_id: 11, evidence_id: 71, remark: "Click-time handout", container_id: 31,
    qr_payloads: ["UNIT-1", "PASTED-1", "PASTED-2"], items: [{ product_id: 5, quantity: 2 }],
  });
});

it.each(["actor", "unmount", "visit"])("paused issue never dispatches after %s departure", async (departure) => {
  const net = hardwareHttp();
  const view = mountHardware(<DirectLoans key="A" makerspace={maker} />);
  await readyDirect();
  onlineManager.setOnline(false);
  fireEvent.click(issueButton());
  await paused(view.client);
  if (departure === "actor") login("B");
  const oldField = field("Issue remark");
  view.rerender(departure === "unmount" ? <p>Left handouts</p> : <DirectLoans key="B" makerspace={maker} />);
  if (departure !== "unmount") {
    await waitFor(() => expect(field("Issue remark")).not.toBe(oldField));
    setValue("Issue remark", "New form draft");
  }
  await resume(view.client);
  expect(issueCalls(net.calls)).toHaveLength(0);
  expect(screen.queryByText(/Handout issued\.|Handout visit changed/)).not.toBeInTheDocument();
  if (departure !== "unmount") expect(field("Issue remark")).toHaveValue("New form draft");
});

it.each(["success", "error"])("old actual issue %s/finally cannot clear or unlock a new actor's pending form", async (outcome) => {
  const oldResponse = held<Response>(); const newResponse = held<Response>(); let issues = 0;
  const net = hardwareHttp((call) => call.method === "POST" && call.path.endsWith("/direct-loans")
    ? ++issues === 1 ? oldResponse.promise : newResponse.promise : undefined);
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await readyDirect();
  fireEvent.click(issueButton());
  await waitFor(() => expect(issues).toBe(1));
  const oldField = field("Issue remark");
  login("B");
  view.rerender(<DirectLoans makerspace={maker} />);
  await waitFor(() => expect(field("Issue remark")).not.toBe(oldField));
  await readyDirect();
  setValue("Borrowing member", "12");
  setValue("Issue remark", "B private handout");
  fireEvent.click(issueButton());
  await waitFor(() => expect(issues).toBe(2));
  await release(oldResponse, outcome === "success" ? json({ id: 81 }) : json({ detail: "Old issue failed" }, 409));
  expect(field("Issue remark")).toHaveValue("B private handout");
  expect(field("Borrowing member")).toHaveValue("12");
  expect(field("Issue remark")).toBeDisabled();
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(screen.queryByText(/Handout issued\.|Old issue failed/)).not.toBeInTheDocument();
  expect(issueCalls(net.calls)).toHaveLength(2);
  await release(newResponse, json({ id: 82 }));
  await screen.findByText("Handout issued.");
  await waitFor(() => expect(field("Product")).toHaveValue(""));
});

it("current error keeps the complete draft for retry, then refreshes the normal loan/inventory caches", async () => {
  let fail = true;
  const net = hardwareHttp((call) => call.method === "POST" && call.path.endsWith("/direct-loans") && fail
    ? json({ detail: "Stock temporarily busy" }, 409) : undefined);
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await readyDirect();
  fireEvent.click(issueButton());
  await screen.findAllByText("Stock temporarily busy");
  await waitFor(() => expect(issueButton()).toBeEnabled());
  expect(field("Product")).toHaveValue("5");
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(field("Issue remark")).toHaveValue("Click-time handout");
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  fail = false;
  fireEvent.click(issueButton());
  await screen.findByText("Handout issued.");
  expect(issueCalls(net.calls)).toHaveLength(2);
  expect(issueCalls(net.calls)[1].body).toEqual(issueCalls(net.calls)[0].body);
  expect(invalidate.mock.calls.map(([filter]) => filter?.queryKey)).toEqual(expect.arrayContaining([
    ["direct-loans", 7], ["inventory-all", 7], ["containers-all", 7], ["dashboard", 7], ["accountability", 7], ["needs-fix-shelf", 7],
  ]));
});

it("containers module off keeps a photo-required counted handout usable without container reads", async () => {
  const net = hardwareHttp();
  mountHardware(<DirectLoans makerspace={{ ...maker, enabled_modules: [] }} />);
  await waitForChoice("Borrower", "11");
  setValue("Borrower", "11");
  setValue("Product", "5");
  expect(issueButton()).toBeDisabled();
  expect(screen.queryByLabelText(/^Container/)).not.toBeInTheDocument();
  expect(net.calls.some((call) => call.path.includes("/containers"))).toBe(false);
  await readyDirect();
  fireEvent.click(issueButton());
  await screen.findByText("Handout issued.");
  expect(issueCalls(net.calls)[0].body).toMatchObject({ container_id: null, evidence_id: 71 });
});

it("individually tracked direct handout uses scanned unit QR rather than a counted manual line", async () => {
  const net = hardwareHttp();
  mountHardware(<DirectLoans makerspace={maker} />);
  await waitForChoice("Borrowing member", "11");
  await waitForChoice("Product", "6");
  setValue("Borrowing member", "11");
  setValue("Product", "6");
  await uploadPhoto();
  expect(issueButton()).toBeDisabled();
  expect(field("Quantity")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  await act(async () => { await scanner.current!.onScan("UNIT-61"); });
  await screen.findByRole("list", { name: "Scanned QR codes" });
  fireEvent.click(issueButton());
  await screen.findByText("Handout issued.");
  expect(issueCalls(net.calls)[0].body).toMatchObject({ borrower_id: 11, evidence_id: 71, items: [], qr_payloads: ["UNIT-61"] });
});

it.each(["success", "error"])("held old QR %s cannot append into the actual post-issue remount", async (outcome) => {
  const qr = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? qr.promise : undefined);
  mountHardware(<DirectLoans makerspace={maker} />);
  await readyDirect();
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  const old = scanner.current!;
  act(() => { void old.onScan("OLD-UNIT"); });
  await waitFor(() => expect(net.calls.some((call) => call.body.payload === "OLD-UNIT")).toBe(true));
  fireEvent.click(issueButton());
  await screen.findByText("Handout issued.");
  await waitFor(() => expect(field("Product")).toHaveValue(""));
  setValue("Issue remark", "Next handout draft");
  setValue("Container", "32");
  await release(qr, outcome === "success" ? json(asset("OLD-UNIT")) : json({ detail: "Obsolete unit error" }, 404));
  await act(async () => { await old.onScan("OLD-NATIVE"); });
  expect(field("Issue remark")).toHaveValue("Next handout draft");
  expect(field("Container")).toHaveValue("32");
  expect(screen.queryByRole("list", { name: "Scanned QR codes" })).not.toBeInTheDocument();
  expect(screen.queryByText("Obsolete unit error")).not.toBeInTheDocument();
  expect(net.calls.filter((call) => call.path === "/admin/qr/resolve")).toHaveLength(1);
});
