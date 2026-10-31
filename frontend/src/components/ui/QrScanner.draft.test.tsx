import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QrScanner from "./QrScanner";

let originalMediaDevices: PropertyDescriptor | undefined;

beforeEach(() => {
  originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalMediaDevices) {
    Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  } else {
    Reflect.deleteProperty(navigator, "mediaDevices");
  }
});

describe("QrScanner pending camera draft", () => {
  it("preserves the typed input through permission denial and submits one trimmed code", async () => {
    let rejectPermission!: (reason: DOMException) => void;
    const permission = new Promise<MediaStream>((_resolve, reject) => {
      rejectPermission = reject;
    });
    const getUserMedia = vi.fn().mockReturnValue(permission);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    const onScan = vi.fn();
    const onClose = vi.fn();
    render(<QrScanner onScan={onScan} onClose={onClose} />);

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(getUserMedia).toHaveBeenCalledWith({ video: { facingMode: "environment" } });
    expect(screen.getByText("Starting camera...")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Type the code" });
    const draft = "  tool-42  ";
    fireEvent.change(input, { target: { value: draft } });
    expect(input).toHaveValue(draft);
    expect(screen.getByRole("button", { name: "Use code" })).toBeEnabled();

    await act(async () => {
      rejectPermission(new DOMException("Permission denied", "NotAllowedError"));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Camera permission was denied. Allow camera access in your browser and try again.",
    );
    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "Type the code" })).toBe(input);
    expect(input).toHaveValue(draft);
    expect(screen.getByRole("button", { name: "Use code" })).toBeEnabled();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(onScan).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Use code" }));
    expect(onScan.mock.calls).toEqual([["tool-42"]]);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onScan.mock.calls).toEqual([["tool-42"]]);
  });
});
