import { forwardRef, useCallback, useEffect, useRef, useState, type ComponentPropsWithoutRef, type ElementRef, type ReactNode, type Ref } from "react";
import { Link, NavLink } from "react-router-dom";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "../../lib/cn";

/* Underline tabs. Radix gives role="tablist"/"tab"/"tabpanel", aria-selected and
   arrow-key / Home / End navigation with a single tab stop. */
/** `min-w-0` so a grid or flex parent can shrink the tabs below their row's natural width;
 *  the list then scrolls sideways instead of widening the page on a phone. */
export const Tabs = forwardRef<ElementRef<typeof TabsPrimitive.Root>, ComponentPropsWithoutRef<typeof TabsPrimitive.Root>>(function Tabs(
  { className, ...props },
  ref,
) {
  return <TabsPrimitive.Root ref={ref} className={cn("min-w-0", className)} {...props} />;
});

const tabListClasses = "flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden";
const tabClasses =
  "relative inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap px-3 text-[15px] font-semibold text-ink-muted transition-colors duration-180 ease-standard hover:text-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:text-ink-disabled after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent [&_svg]:size-4";
const activeTab = "text-ink after:bg-accent-ink";

/**
 * Overflowing tab rows scroll sideways and show a faded arrow on each side that hides
 * tabs. The arrows are pointer-only (tabIndex -1): keyboard users keep the tabs' own
 * arrow-key navigation, which scrolls the focused tab into view.
 */
function useScrollHints<T extends HTMLElement>() {
  const node = useRef<T | null>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const update = useCallback(() => {
    const el = node.current;
    if (!el) return;
    const left = el.scrollLeft > 2;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
    setEdges((current) => (current.left === left && current.right === right ? current : { left, right }));
  }, []);
  useEffect(() => {
    const el = node.current;
    if (!el) return;
    update();
    el.addEventListener("scroll", update, { passive: true });
    if (typeof ResizeObserver === "undefined") return () => el.removeEventListener("scroll", update);
    const observer = new ResizeObserver(update);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => {
      el.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, [update]);
  const scroll = (direction: -1 | 1) => {
    const el = node.current;
    if (!el) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy?.({ left: direction * Math.max(120, el.clientWidth * 0.7), behavior: reduce ? "auto" : "smooth" });
  };
  return { node, edges, scroll };
}

function setRefs<T>(...refs: Array<Ref<T> | undefined>) {
  return (value: T | null) => {
    for (const ref of refs) {
      if (typeof ref === "function") ref(value);
      else if (ref) (ref as { current: T | null }).current = value;
    }
  };
}

function ScrollHint({ side, visible, onClick }: { side: "left" | "right"; visible: boolean; onClick: () => void }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-y-0 z-[1] flex items-center transition-opacity duration-180 ease-standard",
        side === "left" ? "left-0 bg-gradient-to-r from-canvas from-55% to-transparent pr-6" : "right-0 justify-end bg-gradient-to-l from-canvas from-55% to-transparent pl-6",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <button
        type="button"
        tabIndex={-1}
        onClick={onClick}
        className={cn("inline-flex size-8 pointer-coarse:size-11 items-center justify-center rounded-full border border-line bg-canvas text-ink-secondary shadow-segment hover:text-ink", visible && "pointer-events-auto")}
      >
        {side === "left" ? <ChevronLeft className="size-4" /> : <ChevronRight className="size-4" />}
      </button>
    </span>
  );
}

export const TabsList = forwardRef<ElementRef<typeof TabsPrimitive.List>, ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(function TabsList(
  { className, ...props },
  ref,
) {
  const { node, edges, scroll } = useScrollHints<HTMLDivElement>();
  return (
    <div className="relative min-w-0">
      <ScrollHint side="left" visible={edges.left} onClick={() => scroll(-1)} />
      <TabsPrimitive.List ref={setRefs(ref, node)} className={cn(tabListClasses, className)} {...props} />
      <ScrollHint side="right" visible={edges.right} onClick={() => scroll(1)} />
    </div>
  );
});

export const TabsTrigger = forwardRef<ElementRef<typeof TabsPrimitive.Trigger>, ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(function TabsTrigger(
  { className, ...props },
  ref,
) {
  return <TabsPrimitive.Trigger ref={ref} className={cn(tabClasses, "data-[state=active]:text-ink data-[state=active]:after:bg-accent-ink", className)} {...props} />;
});

export const TabsContent = forwardRef<ElementRef<typeof TabsPrimitive.Content>, ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(function TabsContent(
  { className, ...props },
  ref,
) {
  return <TabsPrimitive.Content ref={ref} className={cn("pt-6 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus", className)} {...props} />;
});

export type NavTabItem = {
  to: string;
  label: ReactNode;
  /** Force the active state; otherwise the router decides. */
  active?: boolean;
  /** Match the path exactly (react-router `end`). */
  end?: boolean;
};

/** Link-based underline tabs for moving between routes (aria-current="page" on the active one). */
export function NavTabs({ items, label, className }: { items: NavTabItem[]; label: string; className?: string }) {
  const { node, edges, scroll } = useScrollHints<HTMLElement>();
  return (
    <div className="relative min-w-0">
      <ScrollHint side="left" visible={edges.left} onClick={() => scroll(-1)} />
      <nav ref={node} aria-label={label} className={cn(tabListClasses, className)}>
        {items.map((item) =>
          item.active === undefined ? (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => cn(tabClasses, isActive && activeTab)}>
              {item.label}
            </NavLink>
          ) : (
            <Link key={item.to} to={item.to} aria-current={item.active ? "page" : undefined} className={cn(tabClasses, item.active && activeTab)}>
              {item.label}
            </Link>
          ),
        )}
      </nav>
      <ScrollHint side="right" visible={edges.right} onClick={() => scroll(1)} />
    </div>
  );
}
