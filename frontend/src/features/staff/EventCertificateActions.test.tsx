import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventCertificateActions } from "./EventCertificateActions";
import type { CertificateSummary } from "./eventFeedbackApi";

const mocks = vi.hoisted(() => ({
  download: vi.fn(), revoke: vi.fn(), reissue: vi.fn(), showToast: vi.fn(),
  useCertificateDownload: vi.fn(), useCertificateAction: vi.fn(),
}));

vi.mock("./eventFeedbackApi", () => ({
  useCertificateDownload: mocks.useCertificateDownload,
  useCertificateAction: mocks.useCertificateAction,
}));

vi.mock("../../components/ui", async () => ({
  ...await vi.importActual<typeof import("../../components/ui")>("../../components/ui"),
  useToast: () => ({ showToast: mocks.showToast }),
}));

function renderCertificate(status: CertificateSummary["status"]) {
  const certificate: CertificateSummary = {
    id: 31, status, revision: 2, issued_at: "2026-10-29T10:00:00Z",
    rendered_at: status === "active" ? "2026-10-29T10:01:00Z" : null,
    revoked_at: status === "revoked" ? "2026-10-29T10:02:00Z" : null,
  };
  return render(<EventCertificateActions certificate={certificate} eventId={17} makerspaceId={7} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.useCertificateDownload.mockReturnValue({ mutate: mocks.download, isPending: false, error: null });
  mocks.useCertificateAction.mockImplementation((_eventId, _spaceId, action: string) => ({
    mutate: action === "revoke" ? mocks.revoke : mocks.reissue,
    isPending: false, error: null,
  }));
});

describe("EventCertificateActions", () => {
  it("lets staff stop rendering through a confirmation, with no download or preparation", () => {
    renderCertificate("rendering");

    expect(screen.getByRole("button", { name: "Stop preparation…" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare certificate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reissue" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop preparation…" }));

    const dialog = screen.getByRole("alertdialog", { name: "Stop certificate preparation?" });
    expect(within(dialog).getByText(/including any work still in progress/)).toBeInTheDocument();
    expect(mocks.revoke).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(mocks.revoke).not.toHaveBeenCalled();
    expect(mocks.download).not.toHaveBeenCalled();
    expect(mocks.reissue).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Stop preparation…" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Stop preparation" }));

    expect(mocks.revoke).toHaveBeenCalledExactlyOnceWith(31, expect.objectContaining({
      onSuccess: expect.any(Function), onError: expect.any(Function),
    }));
    expect(mocks.useCertificateAction).toHaveBeenCalledWith(17, 7, "revoke");
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("reissues a revoked certificate using its existing ID", () => {
    renderCertificate("revoked");

    expect(screen.queryByRole("button", { name: /Revoke|Stop preparation|Download|Prepare certificate/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reissue" }));

    expect(mocks.useCertificateAction).toHaveBeenCalledWith(17, 7, "reissue");
    expect(mocks.reissue).toHaveBeenCalledExactlyOnceWith(31, expect.objectContaining({ onSuccess: expect.any(Function) }));
    expect(mocks.revoke).not.toHaveBeenCalled();
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it.each(["pending", "failed"] as const)("allows preparation and confirmed revocation for %s", (status) => {
    renderCertificate(status);

    expect(screen.getByRole("button", { name: "Prepare certificate" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Revoke…" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke certificate?" });
    expect(mocks.revoke).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));

    expect(mocks.revoke).toHaveBeenCalledExactlyOnceWith(31, expect.any(Object));
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("keeps Download and confirmed Revoke for an active certificate", () => {
    renderCertificate("active");

    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Prepare certificate" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    // The hook boundary captures the callback; do not navigate jsdom or a real browser.
    expect(mocks.download).toHaveBeenCalledExactlyOnceWith(31, expect.objectContaining({ onSuccess: expect.any(Function) }));
    expect(mocks.useCertificateDownload).toHaveBeenCalledWith(17, 7);
    fireEvent.click(screen.getByRole("button", { name: "Revoke…" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "Revoke certificate?" })).getByRole("button", { name: "Revoke" }));
    expect(mocks.revoke).toHaveBeenCalledExactlyOnceWith(31, expect.any(Object));
  });
});
