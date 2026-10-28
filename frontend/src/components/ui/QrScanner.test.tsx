import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import QrScanner from "./QrScanner";

function denyCamera(name: string) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("denied", name)) },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("QrScanner camera failure", () => {
  it("explains a denied camera, focuses Close and accepts a typed code", async () => {
    denyCamera("NotAllowedError");
    const onScan = vi.fn();
    render(<QrScanner onScan={onScan} onClose={() => undefined} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/camera permission was denied/i);
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    fireEvent.change(screen.getByLabelText("Type the code"), { target: { value: "  tool-42 " } });
    fireEvent.click(screen.getByRole("button", { name: "Use code" }));
    expect(onScan).toHaveBeenCalledWith("tool-42");
  });

  it("says when there is no camera at all", async () => {
    denyCamera("NotFoundError");
    render(<QrScanner onScan={() => undefined} onClose={() => undefined} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/no camera was found/i);
  });
});
