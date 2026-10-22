import { cn } from "../../lib/cn";

export type ActiveTab = "borrow" | "scan";

/**
 * Two views of one request desk, drawn as a segmented control. Plain buttons with
 * aria-pressed (not tabs): each one swaps the panel below in place. Rendered only where
 * self-checkout can actually work, so a lone borrow form has no dead switch above it.
 */
export function RequestDeskTabs({ activeTab, onChange }: { activeTab: ActiveTab; onChange: (tab: ActiveTab) => void }) {
  function tabClass(tab: ActiveTab) {
    return cn(
      "inline-flex min-h-9 min-w-0 items-center justify-center rounded-full px-3 text-sm font-semibold transition-[background-color,color,box-shadow] duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
      activeTab === tab ? "bg-canvas text-ink shadow-segment" : "text-ink-muted hover:text-ink",
    );
  }

  return (
    <div aria-label="Request actions" className="grid shrink-0 grid-cols-2 gap-1 rounded-full bg-fill p-1" role="group">
      <button
        aria-pressed={activeTab === "borrow"}
        className={tabClass("borrow")}
        id="public-request-borrow-tab"
        type="button"
        onClick={() => onChange("borrow")}
      >
        Borrow request
      </button>
      <button
        aria-pressed={activeTab === "scan"}
        className={tabClass("scan")}
        id="public-request-scan-tab"
        type="button"
        onClick={() => onChange("scan")}
      >
        Scan a tool
      </button>
    </div>
  );
}
