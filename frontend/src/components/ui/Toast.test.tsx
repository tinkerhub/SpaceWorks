import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TOAST_DURATION_MS, ToastProvider, useToast, type ToastOptions } from "./Toast";

function Trigger({ message, options }: { message: string; options?: ToastOptions }) {
  const { showToast } = useToast();
  return (
    <button type="button" onClick={() => showToast(message, options)}>
      Notify
    </button>
  );
}

function renderToast(message: string, options?: ToastOptions) {
  return render(
    <ToastProvider>
      <Trigger message={message} options={options} />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ToastProvider", () => {
  it("announces the message politely and dismisses it after four seconds", () => {
    renderToast("Item saved", { tone: "success" });

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));
    expect(screen.getByRole("status")).toHaveTextContent("Item saved");
    expect(TOAST_DURATION_MS).toBe(4000);

    act(() => {
      vi.advanceTimersByTime(TOAST_DURATION_MS - 1);
    });
    expect(screen.getByText("Item saved")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Item saved")).toBeNull();
  });

  it("announces errors assertively", () => {
    renderToast("Could not save", { tone: "error" });

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save");
  });

  it("keeps both live regions mounted and only changes their content", () => {
    renderToast("Could not save", { tone: "error" });

    // Present before anything is announced, so the first message is not missed.
    const polite = screen.getByRole("status");
    const assertive = screen.getByRole("alert");
    expect(polite).toHaveAttribute("aria-live", "polite");
    expect(assertive).toHaveAttribute("aria-live", "assertive");
    expect(polite).toBeEmptyDOMElement();
    expect(assertive).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));
    expect(screen.getByRole("alert")).toBe(assertive);
    expect(assertive).toHaveTextContent("Could not save");
    expect(polite).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByRole("alert")).toBe(assertive);
    expect(assertive).toBeEmptyDOMElement();
    expect(screen.getByRole("status")).toBe(polite);
  });

  it("runs the optional action once and closes", () => {
    const undo = vi.fn();
    renderToast("Request archived", { action: { label: "Undo", onClick: undo } });

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Request archived")).toBeNull();
  });

  it("can be dismissed early", () => {
    renderToast("Copied");

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Copied")).toBeNull();
  });

  it("is a harmless no-op without a provider", () => {
    render(<Trigger message="Nobody listens" />);
    expect(() => fireEvent.click(screen.getByRole("button", { name: "Notify" }))).not.toThrow();
  });
});
