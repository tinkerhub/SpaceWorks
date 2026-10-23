import { useEffect, useState } from "react";
import { ArrowDown } from "lucide-react";

import { Button } from "../../components/ui";

/**
 * Below md the request desk sits after the whole catalogue, so a borrower who has added
 * items would otherwise scroll past every card to reach it. This pill floats at the bottom
 * while the desk is off screen and jumps to it; it hides once the desk is in view.
 */
export function RequestCartBar({ count, targetId }: { count: number; targetId: string }) {
  const [deskVisible, setDeskVisible] = useState(false);

  useEffect(() => {
    const target = document.getElementById(targetId);
    if (!target || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setDeskVisible(entry.isIntersecting));
    observer.observe(target);
    return () => observer.disconnect();
  }, [targetId]);

  if (count === 0 || deskVisible) return null;

  function jumpToDesk() {
    const target = document.getElementById(targetId);
    if (!target) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    target.focus({ preventScroll: true });
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-[max(1rem,env(safe-area-inset-bottom))] md:hidden">
      <Button variant="primary" className="pointer-events-auto shadow-float" endIcon={<ArrowDown />} onClick={jumpToDesk}>
        Review request · {count} {count === 1 ? "item" : "items"}
      </Button>
    </div>
  );
}
