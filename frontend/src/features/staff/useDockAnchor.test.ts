import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDockAnchor } from "./useDockAnchor";

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) };
}

function dockFixture(top: number) {
  const dock = document.createElement("nav");
  dock.setAttribute("data-staff-dock-root", "");
  const scroller = document.createElement("div");
  scroller.setAttribute("data-staff-dock-scroller", "");
  const anchor = document.createElement("button");
  scroller.append(anchor);
  dock.append(scroller);
  document.body.append(dock);
  vi.spyOn(dock, "getBoundingClientRect").mockReturnValue(rect(12, top - 10, 544, 310 - top));
  const anchorBounds = vi.spyOn(anchor, "getBoundingClientRect").mockReturnValue(rect(460, top, 80, 44));
  return { dock, scroller, anchor, anchorBounds };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useDockAnchor", () => {
  it("keeps a scrollable popover above a tall safe-area dock in short landscape", () => {
    vi.stubGlobal("innerWidth", 568);
    vi.stubGlobal("innerHeight", 320);
    const { dock, anchor } = dockFixture(210);
    const { result } = renderHook(() => useDockAnchor(anchor, true));
    const dockBounds = dock.getBoundingClientRect();
    const popoverBottom = dockBounds.bottom - Number(result.current.bottom);
    const popoverTop = popoverBottom - Number(result.current.maxHeight);

    expect(popoverTop).toBe(16);
    expect(popoverBottom).toBe(202);
    expect(Number(result.current.maxHeight)).toBeGreaterThan(44);
    expect(result.current.maxWidth).toBe(256);
    expect(dockBounds.left + Number(result.current.left)).toBe(296);
  });

  it("recalculates available height and horizontal bounds after resizing or scrolling", () => {
    vi.stubGlobal("innerWidth", 568);
    vi.stubGlobal("innerHeight", 320);
    const { anchor, anchorBounds, scroller } = dockFixture(210);
    const { result } = renderHook(() => useDockAnchor(anchor, true));

    anchorBounds.mockReturnValue(rect(20, 150, 80, 44));
    act(() => scroller.dispatchEvent(new Event("scroll")));
    expect(result.current.maxHeight).toBe(126);
    expect(result.current.left).toBe(4);

    vi.stubGlobal("innerHeight", 568);
    anchorBounds.mockReturnValue(rect(20, 420, 80, 44));
    act(() => window.dispatchEvent(new Event("resize")));
    expect(result.current.maxHeight).toBe(396);
  });

  it("removes listeners while the popover is closed", () => {
    const { anchor, anchorBounds } = dockFixture(210);
    const { result, rerender } = renderHook(({ open }) => useDockAnchor(anchor, open), { initialProps: { open: true } });
    const previousHeight = result.current.maxHeight;

    rerender({ open: false });
    anchorBounds.mockReturnValue(rect(20, 150, 80, 44));
    act(() => window.dispatchEvent(new Event("resize")));

    expect(result.current.maxHeight).toBe(previousHeight);
  });

  it("keeps both popover edges outside landscape notch insets", () => {
    vi.stubGlobal("innerWidth", 568);
    vi.stubGlobal("innerHeight", 320);
    const { dock, anchor, anchorBounds, scroller } = dockFixture(210);
    dock.style.setProperty("--dock-safe-left", "44px");
    dock.style.setProperty("--dock-safe-right", "44px");
    const { result } = renderHook(() => useDockAnchor(anchor, true));

    // Right edge stops one 16px gutter before the 44px unsafe area.
    expect(12 + Number(result.current.left) + 256).toBe(508);
    anchorBounds.mockReturnValue(rect(20, 210, 80, 44));
    act(() => scroller.dispatchEvent(new Event("scroll")));
    expect(12 + Number(result.current.left)).toBe(60);
    expect(result.current.maxHeight).toBe(186);

    vi.stubGlobal("innerWidth", 320);
    act(() => window.dispatchEvent(new Event("resize")));
    expect(result.current.maxWidth).toBe(200);
    expect(12 + Number(result.current.left)).toBe(60);

    dock.style.setProperty("--dock-safe-top", "47px");
    act(() => window.dispatchEvent(new Event("resize")));
    const popoverBottom = dock.getBoundingClientRect().bottom - Number(result.current.bottom);
    expect(popoverBottom - Number(result.current.maxHeight)).toBe(63);
    expect(result.current.maxHeight).toBe(139);
  });
});
