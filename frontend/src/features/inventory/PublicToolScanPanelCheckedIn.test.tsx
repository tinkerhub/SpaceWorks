import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  lookupCheckin,
  publicToolCheckout,
  publicToolReturn,
  requestPublicEvidenceUpload,
  scannerPayload,
  uploadPublicEvidenceFile,
} = vi.hoisted(() => ({
  lookupCheckin: vi.fn(),
  publicToolCheckout: vi.fn(),
  publicToolReturn: vi.fn(),
  requestPublicEvidenceUpload: vi.fn(),
  scannerPayload: { current: "tool-qr-token" },
  uploadPublicEvidenceFile: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, lookupCheckin, publicToolCheckout, publicToolReturn };
});

vi.mock("./selfCheckoutApi", async () => {
  const actual = await vi.importActual<typeof import("./selfCheckoutApi")>(
    "./selfCheckoutApi",
  );
  return { ...actual, requestPublicEvidenceUpload, uploadPublicEvidenceFile };
});

vi.mock("../../components/ui/QrScanner", () => ({
  default: ({ onScan }: { onScan: (value: string) => void }) => (
    <button type="button" onClick={() => onScan(scannerPayload.current)}>
      Complete test scan
    </button>
  ),
}));

import { PublicToolScanPanel } from "./PublicToolScanPanel";

const IDENTITY = {
  mid: 443,
  name: "Ada Example",
  avatar: "",
  purpose: "Working on a project",
  project_name: "Metrocard",
  eligible: true,
  reason: "" as const,
};

function renderPanel(requiresCheckin: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PublicToolScanPanel
        makerspaceSlug="makerspace"
        requiresCheckin={requiresCheckin}
      />
    </QueryClientProvider>,
  );
}

async function confirmIdentity() {
  fireEvent.change(screen.getByLabelText(/your name/i), {
    target: { value: "ada example" },
  });
  fireEvent.click(screen.getByRole("button", { name: /find me/i }));
  await screen.findByText("Metrocard");
}

async function uploadEvidence(label: RegExp) {
  const file = new File(["photo"], "evidence.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
  await waitFor(() => expect(requestPublicEvidenceUpload).toHaveBeenCalled());
  await screen.findByText("Photo uploaded");
}

function scanTool(payload: string, scanAnother = false) {
  scannerPayload.current = payload;
  fireEvent.click(
    screen.getByRole("button", {
      name: scanAnother ? /scan another/i : /scan qr with camera/i,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: /complete test scan/i }));
}

describe("checked-in public tool scanning", () => {
  beforeEach(() => {
    lookupCheckin.mockReset();
    lookupCheckin.mockResolvedValue([IDENTITY]);
    requestPublicEvidenceUpload.mockReset();
    requestPublicEvidenceUpload.mockResolvedValue({
      evidence_id: 91,
      upload_url: "https://storage.example/upload",
      fields: {},
      object_key: "staged/evidence.jpg",
    });
    uploadPublicEvidenceFile.mockReset();
    uploadPublicEvidenceFile.mockResolvedValue(undefined);
    publicToolCheckout.mockReset();
    publicToolCheckout.mockResolvedValue({
      public_token: "loan-token",
      status: "issued",
      items: [],
    });
    publicToolReturn.mockReset();
    publicToolReturn.mockResolvedValue({
      public_token: "loan-token",
      status: "returned",
      items: [],
    });
    scannerPayload.current = "tool-qr-token";
  });

  it("gates evidence and sends the confirmed identity through checkout and return", async () => {
    renderPanel(true);
    expect(screen.getByLabelText(/issue photo/i)).toBeDisabled();

    await confirmIdentity();
    await uploadEvidence(/issue photo/i);
    expect(requestPublicEvidenceUpload).toHaveBeenLastCalledWith(
      "makerspace",
      expect.objectContaining({ checkin_mid: 443, name: "Ada Example" }),
    );

    scanTool("tool-qr-token");
    fireEvent.click(screen.getByRole("button", { name: /^check out 1 tool$/i }));
    await waitFor(() => expect(publicToolCheckout).toHaveBeenCalledTimes(1));
    expect(publicToolCheckout.mock.calls[0][1]).toMatchObject({
      payload: "tool-qr-token",
      evidence_id: 91,
      checkin_mid: 443,
      name: "Ada Example",
    });
    expect(publicToolCheckout.mock.calls[0][1].qr_payloads).toBeUndefined();

    await uploadEvidence(/return photo/i);
    fireEvent.change(screen.getByLabelText(/return condition notes/i), {
      target: { value: "Returned clean" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^return$/i }));
    await waitFor(() => expect(publicToolReturn).toHaveBeenCalledTimes(1));
    expect(publicToolReturn.mock.calls[0][1]).toMatchObject({
      payload: "tool-qr-token",
      evidence_id: 91,
      remark: "Returned clean",
      checkin_mid: 443,
      name: "Ada Example",
    });
  });

  it("keeps legacy evidence bodies free of check-in fields", async () => {
    renderPanel(false);
    await uploadEvidence(/issue photo/i);

    const body = requestPublicEvidenceUpload.mock.calls[0][1];
    expect(body.checkin_mid).toBeUndefined();
    expect(body.name).toBeUndefined();
  });

  it("submits two scans as one checkout carrying both QR payloads", async () => {
    renderPanel(false);
    await uploadEvidence(/issue photo/i);
    scanTool("tool-one");
    scanTool("tool-two", true);

    fireEvent.click(screen.getByRole("button", { name: /^check out 2 tools$/i }));

    await waitFor(() => expect(publicToolCheckout).toHaveBeenCalledTimes(1));
    expect(publicToolCheckout.mock.calls[0][1]).toEqual({
      qr_payloads: ["tool-one", "tool-two"],
      evidence_id: 91,
    });
  });

  it("keeps a single scan on the legacy payload field", async () => {
    renderPanel(false);
    await uploadEvidence(/issue photo/i);
    scanTool("only-tool");

    fireEvent.click(screen.getByRole("button", { name: /^check out 1 tool$/i }));

    await waitFor(() => expect(publicToolCheckout).toHaveBeenCalledTimes(1));
    expect(publicToolCheckout.mock.calls[0][1]).toEqual({
      payload: "only-tool",
      evidence_id: 91,
    });
  });

  it("deduplicates repeated scans", async () => {
    renderPanel(false);
    await uploadEvidence(/issue photo/i);
    scanTool("same-tool");
    scanTool("same-tool", true);

    expect(screen.getAllByRole("button", { name: /remove tool/i })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /^check out 1 tool$/i }));

    await waitFor(() => expect(publicToolCheckout).toHaveBeenCalledTimes(1));
    expect(publicToolCheckout.mock.calls[0][1]).toEqual({
      payload: "same-tool",
      evidence_id: 91,
    });
  });

  it("removes a pending tool from the submitted set", async () => {
    renderPanel(false);
    await uploadEvidence(/issue photo/i);
    scanTool("tool-one");
    scanTool("tool-two", true);
    fireEvent.click(screen.getByRole("button", { name: /remove tool 1/i }));

    fireEvent.click(screen.getByRole("button", { name: /^check out 1 tool$/i }));

    await waitFor(() => expect(publicToolCheckout).toHaveBeenCalledTimes(1));
    expect(publicToolCheckout.mock.calls[0][1]).toEqual({
      payload: "tool-two",
      evidence_id: 91,
    });
  });
});
