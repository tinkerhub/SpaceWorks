import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BoxCodeField } from "./QueuesModalShared";
import {
  box, containers, endHardwareTest, field, hardwareHttp, held, json, login, mountHardware,
  page, release, scanner, setValue, startHardwareTest, waitForChoice,
} from "../../../test/hardwareOwnershipHarness";

vi.mock("../../../components/ui/QrScanner", async () => {
  const { ScannerLeaf } = await import("../../../test/hardwareOwnershipHarness");
  return { default: ScannerLeaf };
});
beforeEach(startHardwareTest);
afterEach(endHardwareTest);
function FieldVisit({ visit = 1, makerId = 7, pending = false }) {
  const [value, setValue] = useState("BOX-B");
  return <><output data-testid="chosen-container">{value}</output>
    <BoxCodeField key={visit} makerspaceId={makerId} pending={pending} value={value} onChange={setValue} /></>;
}

it.each(["success", "error"])("held old container QR %s cannot replace a newer row's choice", async (outcome) => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? response.promise : undefined);
  const view = mountHardware(<FieldVisit />);
  await waitForChoice("Available container", "BOX-A");
  fireEvent.click(screen.getByRole("button", { name: "Scan" }));
  const old = scanner.current!;
  act(() => { void old.onScan("BOX-QR-A"); });
  await waitFor(() => expect(net.calls.filter((call) => call.path === "/admin/qr/resolve")).toHaveLength(1));
  view.rerender(<FieldVisit visit={2} />);
  await waitForChoice("Available container", "BOX-B");
  await release(response, outcome === "success" ? json(box()) : json({ detail: "Old container error" }, 409));
  await act(async () => { await old.onScan("AFTER-UNMOUNT"); });
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("BOX-B");
  expect(screen.queryByText("Old container error")).not.toBeInTheDocument();
  expect(net.calls.filter((call) => call.path === "/admin/qr/resolve")).toHaveLength(1);
});

it("manual/list selection and a current active container scan work; pending blocks retained callbacks and edits", async () => {
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? json(box()) : undefined);
  const view = mountHardware(<FieldVisit />);
  await waitForChoice("Available container", "BOX-A");
  setValue("Available container", "BOX-A");
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("BOX-A");
  fireEvent.click(screen.getByRole("button", { name: "Enter code manually" }));
  setValue("Container code", "MANUAL");
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("MANUAL");
  fireEvent.click(screen.getByRole("button", { name: "Scan" }));
  const old = scanner.current!;
  fireEvent.click(screen.getByRole("button", { name: "Close native scanner" }));
  fireEvent.click(screen.getByRole("button", { name: "Scan" }));
  await act(async () => { await old.onScan("CLOSED"); });
  expect(net.calls.some((call) => call.path === "/admin/qr/resolve")).toBe(false);
  const current = scanner.current!;
  view.rerender(<FieldVisit pending />);
  await act(async () => { await current.onScan("PENDING"); });
  setValue("Container code", "BLOCKED");
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("MANUAL");
  expect(net.calls.some((call) => call.path === "/admin/qr/resolve")).toBe(false);
  view.rerender(<FieldVisit />);
  await act(async () => { await current.onScan("CURRENT"); });
  await waitFor(() => expect(screen.getByTestId("chosen-container")).toHaveTextContent("BOX-A"));
});

it.each(["maker", "epoch", "unmount"])("held list read is suppressed after %s departure", async (departure) => {
  const response = held<Response>(); let reads = 0;
  hardwareHttp((call) => call.method === "GET" && call.path.includes("/containers")
    ? ++reads === 1 ? response.promise : json(page([{ ...containers[1], label: "Current options" }])) : undefined);
  const view = mountHardware(<FieldVisit />);
  await waitFor(() => expect(reads).toBe(1));
  if (departure === "epoch") login("B");
  view.rerender(departure === "unmount" ? <p>Field closed</p> : <FieldVisit makerId={departure === "maker" ? 8 : 7} />);
  if (departure !== "unmount") await waitForChoice("Available container", "BOX-B");
  await release(response, json(page([{ ...containers[0], label: "Obsolete options" }])));
  if (departure !== "unmount") {
    expect(field("Available container").querySelector('option[value="BOX-A"]')).not.toBeInTheDocument();
    expect(field("Available container").querySelector('option[value="BOX-B"]')).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Available container" })).toHaveTextContent("Current options");
  } else expect(screen.queryByLabelText("Available container")).not.toBeInTheDocument();
});

it("list only offers active matching codes", async () => {
  hardwareHttp((call) => call.method === "GET" && call.path.includes("/containers") ? json(page([
    containers[0], { ...containers[1], is_active: false }, { id: 33, code: null, label: "No code" },
  ])) : undefined);
  mountHardware(<FieldVisit />);
  await waitForChoice("Available container", "BOX-A");
  expect(field("Available container").querySelector('option[value="BOX-B"]')).not.toBeInTheDocument();
  expect(field("Available container").querySelectorAll("option")).toHaveLength(2);
});

it("a current QR response resolving after action admission cannot edit the pending container", async () => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path === "/admin/qr/resolve" ? response.promise : undefined);
  const view = mountHardware(<FieldVisit />);
  await waitForChoice("Available container", "BOX-A");
  fireEvent.click(screen.getByRole("button", { name: "Scan" }));
  act(() => { void scanner.current!.onScan("BOX-A-QR"); });
  await waitFor(() => expect(net.calls.some((call) => call.path === "/admin/qr/resolve")).toBe(true));
  view.rerender(<FieldVisit pending />);
  await release(response, json(box()));
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("BOX-B");
  view.rerender(<FieldVisit />);
  setValue("Available container", "BOX-A");
  expect(screen.getByTestId("chosen-container")).toHaveTextContent("BOX-A");
});
