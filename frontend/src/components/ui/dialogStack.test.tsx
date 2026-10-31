import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Modal } from "./Modal";
import QrScanner from "./QrScanner";

type DialogHarnessProps = {
  openerOutside?: boolean;
  showOpener?: boolean;
  showOuter?: boolean;
};

function DialogHarness({
  openerOutside = false,
  showOpener = true,
  showOuter = true,
}: DialogHarnessProps) {
  const [scannerOpen, setScannerOpen] = useState(false);

  const opener = (
    <button type="button" onClick={() => setScannerOpen(true)}>
      Open scanner
    </button>
  );

  return (
    <>
      <button type="button">Behind modal</button>
      {openerOutside && showOpener ? opener : null}
      <Modal open={showOuter} onClose={() => undefined} title="Outer modal">
        <button type="button">Modal fallback</button>
        {!openerOutside && showOpener ? opener : null}
      </Modal>
      {scannerOpen ? <QrScanner onScan={() => undefined} onClose={() => setScannerOpen(false)} /> : null}
    </>
  );
}

function AlwaysMountedModalHarness() {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" onClick={() => setOpen(true)}>Open persistent modal</button>
    <Modal open={open} onClose={() => setOpen(false)} title="Persistent modal">
      <input aria-label="Initial modal field" />
      <button type="button">Second modal control</button>
    </Modal>
  </>;
}

beforeEach(() => {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function openScanner() {
  const opener = screen.getByRole("button", { name: "Open scanner" });
  opener.focus();
  fireEvent.click(opener);
  await screen.findByRole("dialog", { name: "QR scanner" });
  return opener;
}

describe("dialog stack", () => {
  it("DS01 focuses an always-mounted modal on opening and reopening and restores its exact opener", async () => {
    render(<StrictMode><AlwaysMountedModalHarness /></StrictMode>);
    const opener = screen.getByRole("button", { name: "Open persistent modal" });
    expect(screen.queryByRole("dialog", { name: "Persistent modal" })).toBeNull();

    for (let visit = 0; visit < 2; visit += 1) {
      opener.focus();
      fireEvent.click(opener);
      const dialog = screen.getByRole("dialog", { name: "Persistent modal" });
      const firstControl = within(dialog).getByRole("textbox", { name: "Initial modal field" });
      await waitFor(() => expect(document.activeElement).toBe(firstControl));
      expect(dialog).toHaveAttribute("aria-modal", "true");
      expect(dialog.parentElement).not.toHaveAttribute("inert");
      expect(document.querySelectorAll('[aria-modal="true"]')).toHaveLength(1);

      fireEvent.keyDown(document, { key: "Escape" });
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Persistent modal" })).toBeNull());
      expect(document.activeElement).toBe(opener);
    }
  });

  it("closes only the scanner on Escape and restores its exact opener", async () => {
    render(<DialogHarness />);
    const opener = await openScanner();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "QR scanner" })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Outer modal" })).toBeInTheDocument();
    expect(document.activeElement).toBe(opener);
  });

  it("focuses the modal's first control when the scanner opener was removed", async () => {
    const view = render(<DialogHarness />);
    const opener = await openScanner();
    view.rerender(<DialogHarness showOpener={false} />);
    expect(opener.isConnected).toBe(false);

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Modal fallback" })));
    expect(document.activeElement).not.toBe(screen.getByRole("button", { name: "Behind modal" }));
  });

  it("rejects an opener outside the underlying modal", async () => {
    render(<DialogHarness openerOutside />);
    const opener = await openScanner();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Modal fallback" })));
    expect(document.activeElement).not.toBe(opener);
  });

  it("keeps scanner focus when the outer modal unmounts first", async () => {
    const view = render(<DialogHarness />);
    await openScanner();
    const scannerControl = screen.getByRole("button", { name: "Done" });
    scannerControl.focus();

    view.rerender(<DialogHarness showOuter={false} />);

    expect(screen.getByRole("dialog", { name: "QR scanner" })).toBeInTheDocument();
    expect(document.activeElement).toBe(scannerControl);
    expect(document.activeElement?.isConnected).toBe(true);
  });

  it("makes the covered modal layer inert and exposes only the scanner as modal", async () => {
    render(<DialogHarness />);
    await openScanner();

    const modalDialog = screen.getByText("Outer modal").closest('[role="dialog"]');
    const modalLayer = modalDialog?.parentElement;
    expect(modalDialog).not.toHaveAttribute("aria-modal");
    expect(modalLayer).toHaveAttribute("inert");
    expect(screen.getByRole("dialog", { name: "QR scanner" })).toHaveAttribute("aria-modal", "true");
  });
});
