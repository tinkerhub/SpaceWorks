import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DirectLoanItems } from "./DirectLoanItems";
import type { LineDraft, ScannedPayload } from "./DirectLoanTypes";
import {
  field, asset, box, containers, endHardwareTest, hardwareHttp, held, json, mountHardware,
  products, release, scanner, setValue, startHardwareTest,
} from "../../test/hardwareOwnershipHarness";

vi.mock("../../components/ui/QrScanner", async () => {
  const { ScannerLeaf } = await import("../../test/hardwareOwnershipHarness");
  return { default: ScannerLeaf };
});
beforeEach(startHardwareTest);
afterEach(endHardwareTest);
// Real parent React setters deliberately survive the item picker's post-issue remount.
function Parent({ containersOn = true, pending = false }) {
  const [visit, setVisit] = useState(0);
  const [scanned, setScanned] = useState<ScannedPayload[]>([]);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [container, setContainer] = useState("");
  const [payloads, setPayloads] = useState("");
  return <><button onClick={() => { setScanned([]); setContainer("32"); setVisit((value) => value + 1); }}>Next handout</button>
    <output data-testid="selected-container">{container}</output>
    <DirectLoanItems key={visit} disabled={pending} products={products} productsLoading={false}
      containers={containersOn ? containers : null} containersLoading={false} containerId={container}
      onContainerChange={setContainer} lines={lines} setLines={setLines} scanned={scanned} setScanned={setScanned}
      qrPayloads={payloads} onQrPayloadsChange={setPayloads} /></>;
}

it.each(["success", "error"])("old item QR %s cannot append through stable parent setter after remount", async (outcome) => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? response.promise : undefined);
  mountHardware(<Parent />);
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  const old = scanner.current!;
  act(() => { void old.onScan("OLD-ITEM"); });
  await waitFor(() => expect(net.calls).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Next handout" }));
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  const current = scanner.current!;
  await release(response, outcome === "success" ? json(asset("OLD-ITEM")) : json({ detail: "Old item error" }, 404));
  expect(screen.queryByRole("list", { name: "Scanned QR codes" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Old item error|not recognised/i)).not.toBeInTheDocument();
  expect(screen.getByTestId("hardware-scanner")).toBeVisible();
  expect(scanner.current).toBe(current);
  await act(async () => { await old.onScan("AFTER-REMOUNT"); });
  expect(net.calls).toHaveLength(1);
});

it.each(["success", "error"])("old container %s/finally cannot select the next form's container or close its scanner", async (outcome) => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? response.promise : undefined);
  mountHardware(<Parent />);
  fireEvent.click(screen.getByRole("button", { name: "Scan container" }));
  const old = scanner.current!;
  act(() => { void old.onScan("OLD-BOX"); });
  await waitFor(() => expect(net.calls).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Next handout" }));
  fireEvent.click(screen.getByRole("button", { name: "Scan container" }));
  await release(response, outcome === "success" ? json(box()) : json({ detail: "Old box error" }, 409));
  expect(screen.getByTestId("selected-container")).toHaveTextContent("32");
  expect(screen.getByTestId("hardware-scanner")).toBeVisible();
  expect(screen.queryByText("Old box error")).not.toBeInTheDocument();
  await act(async () => { await old.onScan("AFTER-REMOUNT"); });
  expect(net.calls).toHaveLength(1);
});

it("closed native callbacks cannot dispatch; concurrent current assets are both retained", async () => {
  const first = held<Response>(); const second = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? call.body.payload === "UNIT-1" ? first.promise : second.promise : undefined);
  mountHardware(<Parent />);
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  const old = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Close native scanner" }));
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  await act(async () => { await old.onScan("CLOSED"); });
  expect(net.calls).toHaveLength(0);
  act(() => { void scanner.current!.onScan("UNIT-1"); void scanner.current!.onScan("UNIT-2"); });
  await waitFor(() => expect(net.calls).toHaveLength(2));
  await release(second, json(asset("UNIT-2")));
  await release(first, json(asset("UNIT-1")));
  expect(screen.getByRole("button", { name: /Remove Unit: UNIT-1/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /Remove Unit: UNIT-2/ })).toBeVisible();
});

it("current container scan matches the loaded active list and module off removes only container controls", async () => {
  hardwareHttp((call) => call.path === "/admin/qr/resolve" ? json(box()) : undefined);
  const view = mountHardware(<Parent />);
  fireEvent.click(screen.getByRole("button", { name: "Scan container" }));
  await act(async () => { await scanner.current!.onScan("CURRENT-BOX"); });
  expect(screen.getByTestId("selected-container")).toHaveTextContent("31");
  expect(screen.queryByTestId("hardware-scanner")).not.toBeInTheDocument();
  view.rerender(<Parent containersOn={false} />);
  expect(screen.queryByLabelText(/^Container/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Scan container" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add item" }));
  setValue("Product", "6");
  expect(field("Quantity")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Scan QR" })).toBeEnabled();
});
