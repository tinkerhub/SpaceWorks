import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { tenantPublicRequest, camera } = vi.hoisted(() => ({
  tenantPublicRequest: vi.fn(), camera: { capture: undefined as undefined | ((file: File) => void) },
}));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest,
}));
// Only the native camera leaf is replaced; uploader admission and storage helper remain real.
vi.mock("../../components/ui/CameraCapture", () => ({
  CameraCapture: ({ open, onCapture }: { open: boolean; onCapture: (file: File) => void }) => {
    if (open) camera.capture = onCapture;
    return open ? <p>Native camera open</p> : null;
  },
}));
import { lendingClient, photo, resetLendingSession } from "../../test/publicLendingHarness";
import { RegressionProviders } from "../../test/uiRegressionHarness";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";

beforeEach(() => {
  resetLendingSession(); tenantPublicRequest.mockReset(); camera.capture = undefined;
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("captured public evidence camera callbacks", () => {
  it.each(["maker change", "unmount"] as const)("a stale native camera callback after %s cannot start a presign or publish evidence", async (transition) => {
    const publish = vi.fn();
    const client = lendingClient();
    const view = render(<PublicEvidenceUpload slug="a" evidenceType="issue" onUploaded={publish} />, {
      wrapper: ({ children }) => <RegressionProviders client={client}>{children}</RegressionProviders>,
    });
    fireEvent.click(screen.getByRole("button", { name: "Take Issue photo" }));
    expect(screen.getByText("Native camera open")).toBeInTheDocument();
    const staleCapture = camera.capture;
    expect(staleCapture).toBeTypeOf("function");
    if (transition === "unmount") view.unmount();
    else view.rerender(<PublicEvidenceUpload slug="b" evidenceType="return" onUploaded={publish} />);
    publish.mockClear();
    await act(async () => { staleCapture!(photo()); });
    expect(tenantPublicRequest).not.toHaveBeenCalled();
    expect(publish).not.toHaveBeenCalled();
  });
});
