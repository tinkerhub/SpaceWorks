import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EvidenceUpload } from "./EvidenceUpload";
import {
  chooseFile, cleanUploadSession, evidenceContract, held, http, json, login, mountStaff,
  noContent, photo, release, resetUploadSession, storageUrl,
} from "../../../test/staffUploadHarness";

const { camera } = vi.hoisted(() => ({ camera: { capture: null as null | ((file: File) => void), close: null as null | (() => void) } }));
vi.mock("../../../components/ui/CameraCapture", () => ({
  CameraCapture: ({ open, onCapture, onClose }: { open: boolean; onCapture: (file: File) => void; onClose: () => void }) => {
    if (open) { camera.capture = onCapture; camera.close = onClose; }
    return open ? <p>Native evidence camera</p> : null;
  },
}));
beforeEach(() => {
  resetUploadSession(); camera.capture = null; camera.close = null;
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
});
afterEach(() => { cleanUploadSession(); });
const props = { makerspaceId: 7, evidenceType: "issue" as const, resourceContext: 1 };

it.each(["PUT", "POST"])("current %s evidence publishes the correct ID, metadata and no app bearer to storage", async (method) => {
  const publish = vi.fn();
  const net = http((call) => call.path === storageUrl ? noContent() : json(evidenceContract(method, 71)));
  mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(publish).toHaveBeenLastCalledWith(71));
  expect(net.calls[0]).toMatchObject({ path: "/admin/makerspaces/7/uploads/evidence-url", body: {
    evidence_type: "issue", content_type: "image/png", size_bytes: photo.size,
  } });
  const raw = net.calls.find((call) => call.path === storageUrl)!;
  expect(raw.method).toBe(method);
  expect(new Headers(raw.init.headers).has("Authorization")).toBe(false);
  if (method === "PUT") expect(raw.init.body).toBe(photo);
  else {
    expect(raw.init.body).toBeInstanceOf(FormData);
    expect((raw.init.body as FormData).get("file")).toBe(photo);
    expect((raw.init.body as FormData).get("policy")).toBe("signed-policy");
  }
});

it.each(["presign", "bytes"])("same-maker request switch fences held %s before B publication", async (stage) => {
  const gate = held<Response>();
  const publishA = vi.fn(); const publishB = vi.fn();
  let hold = true;
  const net = http((call) => {
    if (hold && (stage === "bytes" ? call.path === storageUrl : call.path.endsWith("evidence-url"))) return gate.promise;
    return call.path === storageUrl ? noContent() : json(evidenceContract("PUT", 72));
  });
  const view = mountStaff(<EvidenceUpload {...props} onUploaded={publishA} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(net.calls.some((call) => stage === "bytes" ? call.path === storageUrl : call.path.endsWith("evidence-url"))).toBe(true));
  view.rerender(<EvidenceUpload {...props} resourceContext={2} onUploaded={publishB} />);
  expect(publishB).toHaveBeenCalledExactlyOnceWith(null); // Semantic reset runs in layout during this render.
  publishB.mockClear(); publishA.mockClear(); hold = false;
  await release(gate, stage === "bytes" ? noContent() : json(evidenceContract("PUT", 71)));
  expect(publishA).not.toHaveBeenCalled(); expect(publishB).not.toHaveBeenCalled();
  expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
  if (stage === "presign") expect(net.calls.some((call) => call.path === storageUrl)).toBe(false);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(publishB).toHaveBeenLastCalledWith(72));
});

it("old raw failure cannot clear B's already uploaded evidence or toast", async () => {
  const rawA = held<Response>();
  let bytes = 0;
  const publishA = vi.fn(); const publishB = vi.fn();
  const net = http((call) => call.path === storageUrl ? (++bytes === 1 ? rawA.promise : noContent()) : json(evidenceContract("PUT", 72)));
  const view = mountStaff(<EvidenceUpload {...props} onUploaded={publishA} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(bytes).toBe(1));
  view.rerender(<EvidenceUpload {...props} resourceContext={2} onUploaded={publishB} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(publishB).toHaveBeenLastCalledWith(72));
  const callsB = publishB.mock.calls.length;
  await release(rawA, new Response(null, { status: 503 }));
  expect(publishB).toHaveBeenCalledTimes(callsB);
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(screen.queryByText(/Photo upload failed/)).not.toBeInTheDocument();
  expect(net.calls.filter((call) => call.path === storageUrl)).toHaveLength(2);
});

it("callback identity and disabled flips retain evidence, but disabled file events cannot admit more work", async () => {
  const net = http((call) => call.path === storageUrl ? noContent() : json(evidenceContract()));
  const first = vi.fn(); const next = vi.fn();
  const view = mountStaff(<EvidenceUpload {...props} onUploaded={first} />);
  chooseFile("issue photo", photo);
  await screen.findByText("Photo uploaded");
  view.rerender(<EvidenceUpload {...props} onUploaded={next} />);
  expect(next).not.toHaveBeenCalled();
  view.rerender(<EvidenceUpload {...props} disabled onUploaded={next} />);
  chooseFile("issue photo", photo);
  expect(next).not.toHaveBeenCalled();
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(net.calls.filter((call) => call.path.endsWith("evidence-url"))).toHaveLength(1);
});

it("a disabled flip does not cancel an already admitted current upload", async () => {
  const raw = held<Response>(); const publish = vi.fn();
  const net = http((call) => call.path === storageUrl ? raw.promise : json(evidenceContract()));
  const view = mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(net.calls.some((call) => call.path === storageUrl)).toBe(true));
  view.rerender(<EvidenceUpload {...props} disabled onUploaded={publish} />);
  await release(raw, noContent());
  await waitFor(() => expect(publish).toHaveBeenLastCalledWith(51));
});

it.each(["epoch", "unmount"])("held raw success after %s cannot publish", async (change) => {
  const raw = held<Response>(); const publish = vi.fn();
  const net = http((call) => call.path === storageUrl ? raw.promise : json(evidenceContract()));
  const view = mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  chooseFile("issue photo", photo);
  await waitFor(() => expect(net.calls.some((call) => call.path === storageUrl)).toBe(true));
  if (change === "epoch") { login("B"); view.rerender(<EvidenceUpload {...props} onUploaded={publish} />); }
  else view.unmount();
  publish.mockClear();
  await release(raw, noContent());
  expect(publish).not.toHaveBeenCalled();
});

it.each(["closed", "disabled", "resource", "unmount"])("%s native capture cannot begin evidence upload", async (change) => {
  const net = http(() => json(evidenceContract()));
  const publish = vi.fn(); const view = mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  fireEvent.click(screen.getByRole("button", { name: "Take issue photo" }));
  const capture = camera.capture!;
  expect(capture).toBeTypeOf("function");
  if (change === "closed") act(() => camera.close!());
  if (change === "disabled") view.rerender(<EvidenceUpload {...props} disabled onUploaded={publish} />);
  if (change === "resource") view.rerender(<EvidenceUpload {...props} resourceContext={2} onUploaded={publish} />);
  if (change === "unmount") view.unmount();
  publish.mockClear();
  await act(async () => { capture(photo); });
  expect(net.calls).toHaveLength(0); expect(publish).not.toHaveBeenCalled();
});

it("current native capture returns its ID and closes without allowing replay", async () => {
  const publish = vi.fn();
  const net = http((call) => call.path === storageUrl ? noContent() : json(evidenceContract()));
  mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  fireEvent.click(screen.getByRole("button", { name: "Take issue photo" }));
  const capture = camera.capture!;
  await act(async () => { capture(photo); });
  await waitFor(() => expect(publish).toHaveBeenLastCalledWith(51));
  expect(screen.queryByText("Native evidence camera")).not.toBeInTheDocument();
  await act(async () => { capture(photo); });
  expect(net.calls.filter((call) => call.path.endsWith("evidence-url"))).toHaveLength(1);
});

it("same-tick duplicate admissions send only one presign and remain retryable after current failure", async () => {
  const presign = held<Response>(); let hold = true;
  const publish = vi.fn();
  const net = http((call) => call.path === storageUrl ? noContent() : hold ? presign.promise : json(evidenceContract()));
  mountStaff(<EvidenceUpload {...props} onUploaded={publish} />);
  act(() => { chooseFile("issue photo", photo); chooseFile("issue photo", photo); });
  await waitFor(() => expect(net.calls).toHaveLength(1));
  await release(presign, json({ detail: "Presign unavailable" }, 503));
  await screen.findByText("Presign unavailable");
  hold = false;
  chooseFile("issue photo", photo);
  await waitFor(() => expect(publish).toHaveBeenLastCalledWith(51));
  expect(net.calls.filter((call) => call.path.endsWith("evidence-url"))).toHaveLength(2);
});
