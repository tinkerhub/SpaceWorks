import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ImageUploader } from "./ImageUploader";
import {
  chooseFile, cleanUploadSession, held, http, imageContract, json, login, mountStaff,
  noContent, photo, release, resetUploadSession, storageUrl,
} from "../../test/staffUploadHarness";

const { camera } = vi.hoisted(() => ({ camera: { capture: null as null | ((file: File) => void), close: null as null | (() => void) } }));
vi.mock("../../components/ui/CameraCapture", () => ({
  CameraCapture: ({ open, onCapture, onClose }: { open: boolean; onCapture: (file: File) => void; onClose: () => void }) => {
    if (open) { camera.capture = onCapture; camera.close = onClose; }
    return open ? <p>Native camera</p> : null;
  },
}));
beforeEach(() => {
  resetUploadSession();
  camera.capture = null; camera.close = null;
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:owned-B");
    static revokeObjectURL = vi.fn();
  });
});
afterEach(() => { cleanUploadSession(); });
const base = { endpoint: "/admin/items/1/image", label: "Item photo", currentUrl: "https://images.test/A", onChanged: vi.fn() };
function currentResponder(call: { path: string; method: string }) {
  if (call.path === "/config") return json({ public_image_max_bytes: 1024 });
  if (call.path === storageUrl) return noContent();
  return json(call.method === "POST" ? imageContract() : {});
}

it.each(["endpoint", "project", "clear query", "epoch", "unmount"])("held raw bytes cannot publish after %s departure", async (departure) => {
  const raw = held<Response>();
  const changedA = vi.fn(); const changedB = vi.fn();
  let hold = true;
  const net = http((call) => call.path === storageUrl && hold ? raw.promise : currentResponder(call));
  const view = mountStaff(<ImageUploader {...base} onChanged={changedA} extraBody={{ project_id: 1 }} />);
  chooseFile("Item photo", photo);
  await waitFor(() => expect(net.calls.some((call) => call.path === storageUrl)).toBe(true));
  if (departure === "epoch") login("B");
  if (departure === "unmount") view.unmount();
  else view.rerender(<ImageUploader {...base} onChanged={changedB} currentUrl="https://images.test/B"
    endpoint={departure === "endpoint" ? "/admin/items/2/image" : base.endpoint}
    extraBody={{ project_id: departure === "project" ? 2 : 1 }} clearQuery={departure === "clear query" ? "?project_id=2" : ""} />);
  hold = false;
  await release(raw, noContent());
  expect(net.calls.filter((call) => call.method === "PUT" && call.path !== storageUrl)).toHaveLength(0);
  expect(changedA).not.toHaveBeenCalled(); expect(changedB).not.toHaveBeenCalled();
  expect(screen.queryByText("Item photo updated")).not.toBeInTheDocument();
  if (departure !== "unmount") expect(screen.getByRole("img", { name: "Item photo" })).toHaveAttribute("src", "https://images.test/B");
});

it("already-dispatched attach completion cannot replace B preview, toast or call B callback", async () => {
  const attach = held<Response>();
  const changedB = vi.fn();
  const net = http((call) => call.method === "PUT" && call.path === base.endpoint ? attach.promise : currentResponder(call));
  const view = mountStaff(<ImageUploader {...base} />);
  chooseFile("Item photo", photo);
  await waitFor(() => expect(net.calls.some((call) => call.path === base.endpoint && call.method === "PUT")).toBe(true));
  view.rerender(<ImageUploader {...base} endpoint="/admin/items/2/image" currentUrl="https://images.test/B" onChanged={changedB} />);
  await release(attach, json({}));
  expect(changedB).not.toHaveBeenCalled();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.getByRole("img", { name: "Item photo" })).toHaveAttribute("src", "https://images.test/B");
});

it("late removal cannot revoke the next owner's local object URL", async () => {
  const remove = held<Response>();
  const changedA = vi.fn(); const changedB = vi.fn();
  const net = http((call) => call.method === "DELETE" ? remove.promise : currentResponder(call));
  const view = mountStaff(<ImageUploader {...base} clearQuery="?project_id=1" onChanged={changedA} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(net.calls.some((call) => call.method === "DELETE")).toBe(true));
  expect(net.calls.find((call) => call.method === "DELETE")?.path).toBe(`${base.endpoint}?project_id=1`);
  view.rerender(<ImageUploader {...base} endpoint="/admin/items/2/image" onChanged={changedB} />);
  chooseFile("Item photo", photo);
  await waitFor(() => expect(changedB).toHaveBeenCalledTimes(1));
  await release(remove, json({}));
  expect(changedA).not.toHaveBeenCalled();
  expect(changedB).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("img", { name: "Item photo" })).toHaveAttribute("src", "blob:owned-B");
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith("blob:owned-B");
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:owned-B");
});

it("callback identity rerender retains a valid local preview and current remove still works", async () => {
  http(currentResponder);
  const changed = vi.fn();
  const view = mountStaff(<ImageUploader {...base} onChanged={changed} />);
  chooseFile("Item photo", photo);
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  const replacement = vi.fn();
  view.rerender(<ImageUploader {...base} onChanged={replacement} />);
  expect(screen.getByRole("img", { name: "Item photo" })).toHaveAttribute("src", "blob:owned-B");
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(replacement).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("img", { name: "Item photo" })).not.toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:owned-B");
});

it.each(["closed", "disabled", "resource", "unmount"])("obsolete %s native capture cannot admit work", async (transition) => {
  const net = http(currentResponder);
  const view = mountStaff(<ImageUploader {...base} />);
  fireEvent.click(screen.getByRole("button", { name: "Take Item photo photo" }));
  const capture = camera.capture!;
  expect(capture).toBeTypeOf("function");
  if (transition === "closed") act(() => camera.close!());
  if (transition === "disabled") view.rerender(<ImageUploader {...base} disabled />);
  if (transition === "resource") view.rerender(<ImageUploader {...base} extraBody={{ project_id: 2 }} />);
  if (transition === "unmount") view.unmount();
  await act(async () => { capture(photo); });
  expect(net.calls).toHaveLength(0);
});

it("current native capture uploads once and the closed camera callback cannot submit again", async () => {
  const changed = vi.fn(); const net = http(currentResponder);
  mountStaff(<ImageUploader {...base} onChanged={changed} />);
  fireEvent.click(screen.getByRole("button", { name: "Take Item photo photo" }));
  const capture = camera.capture!;
  await act(async () => { capture(photo); });
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("Native camera")).not.toBeInTheDocument();
  await act(async () => { capture(photo); });
  expect(net.calls.filter((call) => call.path === base.endpoint && call.method === "POST")).toHaveLength(1);
});

it("synchronously blocks duplicate file admissions and permits explicit current retry", async () => {
  const bytes = held<Response>();
  let attempt = 0;
  const changed = vi.fn();
  const net = http((call) => call.path === storageUrl && ++attempt === 1 ? bytes.promise : currentResponder(call));
  mountStaff(<ImageUploader {...base} onChanged={changed} />);
  act(() => { chooseFile("Item photo", photo); chooseFile("Item photo", photo); });
  await waitFor(() => expect(net.calls.filter((call) => call.path === storageUrl)).toHaveLength(1));
  await release(bytes, new Response(null, { status: 503 }));
  expect(await screen.findAllByText(/Storage upload failed/)).not.toHaveLength(0);
  chooseFile("Item photo", photo);
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(net.calls.filter((call) => call.path === storageUrl)).toHaveLength(2);
});

it.each(["upload", "remove"])("late %s failure cannot report into B or alter B's preview", async (operation) => {
  const old = held<Response>();
  const changedA = vi.fn(); const changedB = vi.fn();
  const net = http((call) => (operation === "upload" ? call.path === storageUrl : call.method === "DELETE") ? old.promise : currentResponder(call));
  const view = mountStaff(<ImageUploader {...base} onChanged={changedA} />);
  if (operation === "upload") chooseFile("Item photo", photo);
  else fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(net.calls.some((call) => operation === "upload" ? call.path === storageUrl : call.method === "DELETE")).toBe(true));
  view.rerender(<ImageUploader {...base} endpoint="/admin/items/2/image" currentUrl="https://images.test/B" onChanged={changedB} />);
  await release(old, operation === "upload" ? new Response(null, { status: 503 }) : json({ detail: "Old remove rejected" }, 409));
  expect(changedA).not.toHaveBeenCalled(); expect(changedB).not.toHaveBeenCalled();
  expect(screen.queryByText(/Storage upload failed|Old remove rejected/)).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Item photo" })).toHaveAttribute("src", "https://images.test/B");
  expect(screen.getByLabelText("Item photo")).toBeEnabled();
});
