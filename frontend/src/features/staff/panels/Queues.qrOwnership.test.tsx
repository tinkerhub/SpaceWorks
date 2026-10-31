import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Queues } from "./Queues";
import {
  field, asset, dialog, endHardwareTest, hardwareHttp, held, json, maker, mountHardware,
  queueAction, release, requestA, requestB, scanAsset, scanner,
  setValue, startHardwareTest, uploadPhoto,
} from "../../../test/hardwareOwnershipHarness";

vi.mock("../../../components/ui/QrScanner", async () => {
  const { ScannerLeaf } = await import("../../../test/hardwareOwnershipHarness");
  return { default: ScannerLeaf };
});
beforeEach(startHardwareTest);
afterEach(endHardwareTest);
const panel = () => <Queues makerspace={maker} guestOnly={false} canIssueRequest canReturnRequest canReviewRequests />;

it.each(["B", "A-again"])("held A resolution cannot publish into %s with the same product and line ID", async (visit) => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? response.promise : undefined);
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  await scanAsset("OLD-A");
  await waitFor(() => expect(net.calls.filter((call) => call.path === "/admin/qr/resolve")).toHaveLength(1));
  fireEvent.click(dialog().getByRole("button", { name: "Cancel" }));
  queueAction("Borrower B");
  await screen.findByRole("heading", { name: "Issue request #2" });
  setValue("Remark", "B private draft");
  if (visit === "A-again") {
    fireEvent.click(dialog().getByRole("button", { name: "Cancel" }));
    queueAction("Borrower A");
    await screen.findByRole("heading", { name: "Issue request #1" });
    setValue("Remark", "A second visit");
  }
  await release(response, json(asset("OLD-A")));
  expect(screen.queryByRole("button", { name: "Remove OLD-A" })).not.toBeInTheDocument();
  expect(field("Remark")).toHaveValue(visit === "B" ? "B private draft" : "A second visit");
  expect(screen.getByRole("heading", { name: "Asset QR codes (0/2)" })).toBeVisible();
});

it("ordinary same-row refetch preserves the current draft, uploaded photo and concurrent unit scans", async () => {
  const first = held<Response>(); const second = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve"
    ? call.body.payload === "UNIT-1" ? first.promise : second.promise : undefined);
  const view = mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  setValue("Remark", "Keep my draft");
  await uploadPhoto();
  await scanAsset("UNIT-1");
  await scanAsset("UNIT-2");
  await waitFor(() => expect(net.calls.filter((call) => call.path === "/admin/qr/resolve")).toHaveLength(2));
  await release(second, json(asset("UNIT-2")));
  await release(first, json(asset("UNIT-1")));
  await screen.findByRole("heading", { name: "Asset QR codes (2/2)" });
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["accepted", maker.id] }); });
  expect(field("Remark")).toHaveValue("Keep my draft");
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(screen.getByRole("button", { name: "Remove UNIT-1" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Remove UNIT-2" })).toBeVisible();
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await waitFor(() => expect(net.calls.some((call) => call.path === "/admin/requests/1/issue")).toBe(true));
  expect(net.calls.find((call) => call.path === "/admin/requests/1/issue")?.body).toEqual({
    evidence_id: 71, remark: "Keep my draft", rejects: [], asset_qr_payloads: ["UNIT-2", "UNIT-1"],
  });
  expect(net.calls.some((call) => call.path.endsWith("/assign-box"))).toBe(false);
});

it("closed native scanner callbacks cannot dispatch in a later opening or row visit", async () => {
  const net = hardwareHttp();
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  fireEvent.click(dialog().getByRole("button", { name: "Scan asset QR" }));
  const closed = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Close native scanner" }));
  fireEvent.click(dialog().getByRole("button", { name: "Scan asset QR" }));
  await act(async () => { await closed.onScan("CLOSED"); });
  expect(net.calls.some((call) => call.path === "/admin/qr/resolve")).toBe(false);
  const departed = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Close native scanner" }));
  fireEvent.click(dialog().getByRole("button", { name: "Cancel" }));
  queueAction("Borrower B");
  await act(async () => { await departed.onScan("DEPARTED"); });
  expect(net.calls.some((call) => call.path === "/admin/qr/resolve")).toBe(false);
  expect(requestA.items[0].id).toBe(requestB.items[0].id);
});

it("exact unit count and photo remain required when no container is selected", async () => {
  const net = hardwareHttp();
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  expect(screen.getByText("Upload an issue photo before issuing.")).toBeVisible();
  await uploadPhoto();
  await scanAsset("UNIT-1");
  await screen.findByRole("button", { name: "Remove UNIT-1" });
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  expect(screen.getByText(/Scan exactly 2 asset QR code/)).toBeVisible();
  expect(net.calls.some((call) => call.path.endsWith("/issue"))).toBe(false);
  await scanAsset("UNIT-2");
  await screen.findByRole("button", { name: "Remove UNIT-2" });
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await waitFor(() => expect(net.calls.filter((call) => call.path.endsWith("/issue"))).toHaveLength(1));
});
