import { useLayoutEffect, useState, type CSSProperties } from "react";

const POPOVER_WIDTH = 256;
const VIEWPORT_GUTTER = 16;
const ANCHOR_GAP = 8;

export type DockPopoverPosition = Pick<CSSProperties, "bottom" | "left" | "maxHeight" | "maxWidth">;

export function useDockAnchor(anchor: HTMLButtonElement | null, open: boolean): DockPopoverPosition {
  const [position, setPosition] = useState<DockPopoverPosition>({
    bottom: 0,
    left: VIEWPORT_GUTTER,
  });

  useLayoutEffect(() => {
    if (!open || !anchor) return undefined;

    const updatePosition = () => {
      const bounds = anchor.getBoundingClientRect();
      const dock = anchor.closest<HTMLElement>("[data-staff-dock-root]");
      const dockBounds = dock?.getBoundingClientRect();
      const dockStyle = dock ? window.getComputedStyle(dock) : null;
      const topGutter = VIEWPORT_GUTTER + (Number.parseFloat(dockStyle?.getPropertyValue("--dock-safe-top") ?? "") || 0);
      const leftGutter = VIEWPORT_GUTTER + (Number.parseFloat(dockStyle?.getPropertyValue("--dock-safe-left") ?? "") || 0);
      const rightGutter = VIEWPORT_GUTTER + (Number.parseFloat(dockStyle?.getPropertyValue("--dock-safe-right") ?? "") || 0);
      const availableWidth = Math.max(0, window.innerWidth - leftGutter - rightGutter);
      const popoverWidth = Math.min(POPOVER_WIDTH, availableWidth);
      const idealLeft = bounds.left + (bounds.width / 2) - (popoverWidth / 2);
      const maximumLeft = Math.max(leftGutter, window.innerWidth - popoverWidth - rightGutter);
      const viewportLeft = Math.min(Math.max(leftGutter, idealLeft), maximumLeft);

      setPosition({
        bottom: (dockBounds?.bottom ?? window.innerHeight) - bounds.top + ANCHOR_GAP,
        left: viewportLeft - (dockBounds?.left ?? 0),
        maxWidth: popoverWidth,
        // Measure the space ABOVE the trigger: safe-area padding and wrapped/zoomed
        // dock controls can make the dock taller than a fixed viewport deduction.
        maxHeight: Math.max(0, bounds.top - ANCHOR_GAP - topGutter),
      });
    };

    const scroller = anchor.closest<HTMLElement>("[data-staff-dock-scroller]");
    updatePosition();
    scroller?.addEventListener("scroll", updatePosition, { passive: true });
    window.addEventListener("resize", updatePosition);

    return () => {
      scroller?.removeEventListener("scroll", updatePosition);
      window.removeEventListener("resize", updatePosition);
    };
  }, [anchor, open]);

  return position;
}
