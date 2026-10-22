import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppErrorBoundary } from "./AppErrorBoundary";

let shouldThrow = true;

function Flaky() {
  if (shouldThrow) throw new Error("render exploded");
  return <p>Recovered content</p>;
}

beforeEach(() => {
  shouldThrow = true;
  // React logs caught render errors; keep the test output readable.
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => vi.restoreAllMocks());

describe("AppErrorBoundary", () => {
  it("shows a friendly fallback instead of a blank page and retries on request", () => {
    render(<AppErrorBoundary><Flaky /></AppErrorBoundary>);

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Recovered content")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders its children untouched when nothing fails", () => {
    shouldThrow = false;
    render(<AppErrorBoundary><Flaky /></AppErrorBoundary>);
    expect(screen.getByText("Recovered content")).toBeInTheDocument();
  });
});
