import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RequestCartBar } from "./RequestCartBar";

function Page({ count }: { count: number }) {
  return (
    <>
      <div id="desk" tabIndex={-1}>Request desk</div>
      <RequestCartBar count={count} targetId="desk" />
    </>
  );
}

describe("RequestCartBar", () => {
  it("stays hidden while nothing is selected", () => {
    render(<Page count={0} />);
    expect(screen.queryByRole("button", { name: /review request/i })).not.toBeInTheDocument();
  });

  it("jumps to the request desk and moves focus there", () => {
    render(<Page count={2} />);
    const desk = screen.getByText("Request desk");
    const scroll = vi.spyOn(desk, "scrollIntoView");

    fireEvent.click(screen.getByRole("button", { name: "Review request · 2 items" }));

    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ block: "start" }));
    expect(desk).toHaveFocus();
  });

  it("uses the singular for one item", () => {
    render(<Page count={1} />);
    expect(screen.getByRole("button", { name: "Review request · 1 item" })).toBeInTheDocument();
  });
});
