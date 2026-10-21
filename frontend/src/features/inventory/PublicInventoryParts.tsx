import type { ReactNode } from "react";

import { Button, EmptyState as EmptyCard, FilterChip, Skeleton } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import type { PublicCategory } from "../../types/inventory";

export { formatSlug } from "./useMakerspacePublic";

export type View =
  | { kind: "all" }
  | { kind: "sort"; sort: "popular" | "most_used" }
  | { kind: "category"; slug: string };

/** Card-shaped placeholders while the catalog loads, so the grid never flashes blank. */
export function LoadingState() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading items">
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className="overflow-hidden rounded-lg border border-line bg-canvas">
          <Skeleton className="aspect-[4/3] w-full rounded-none" />
          <div className="space-y-2 p-4">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ query, onClear }: { query: string; onClear?: () => void }) {
  return (
    <EmptyCard
      title={query ? "No matching items" : "No public items yet"}
      description={
        query
          ? "Try a different search term, or clear the search to see everything."
          : "This makerspace has not shared any inventory items publicly."
      }
      action={query && onClear ? <Button onClick={onClear}>Clear search</Button> : undefined}
    />
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <EmptyCard
      tone="error"
      title={error.message}
      description="This makerspace may not exist or its public inventory is turned off."
    />
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <FilterChip selected={active} onClick={onClick} className="shrink-0 whitespace-nowrap">
      {children}
    </FilterChip>
  );
}

/** Browse filters as one scrollable row of chips: the three views, then every category. */
export function CatalogFilters({
  categories,
  view,
  onSelect,
}: {
  categories: PublicCategory[];
  view: View;
  onSelect: (view: View) => void;
}) {
  return (
    <nav aria-label="Catalog browse" className="-mx-4 min-w-0 sm:mx-0">
      <div className="flex gap-2 overflow-x-auto px-4 pb-1 sm:flex-wrap sm:overflow-visible sm:px-0">
        <Chip active={view.kind === "all"} onClick={() => onSelect({ kind: "all" })}>All items</Chip>
        <Chip active={view.kind === "sort" && view.sort === "popular"} onClick={() => onSelect({ kind: "sort", sort: "popular" })}>
          Popular
        </Chip>
        <Chip active={view.kind === "sort" && view.sort === "most_used"} onClick={() => onSelect({ kind: "sort", sort: "most_used" })}>
          Most used
        </Chip>
        {categories.length > 0 ? <span aria-hidden="true" className="mx-1 w-px shrink-0 self-stretch bg-line" /> : null}
        {categories.map((category) => {
          const active = view.kind === "category" && view.slug === category.slug;
          return (
            <Chip key={category.id} active={active} onClick={() => onSelect({ kind: "category", slug: category.slug })}>
              <span className="max-w-[16ch] truncate">{category.name}</span>
              <span className={active ? "tabular-nums opacity-80" : "tabular-nums text-ink-muted"}>{category.product_count}</span>
            </Chip>
          );
        })}
      </div>
    </nav>
  );
}

/**
 * Load failure for a public list (machines, events, bookings): what went wrong in plain
 * words, plus Retry unless retrying cannot help (module off, makerspace missing).
 */
export function PublicLoadError({ error, noun, onRetry }: { error: Error; noun: string; onRetry: () => void }) {
  const apiError = error instanceof StructuredApiError ? error : null;
  const status = apiError?.status;
  const detail = apiError?.detail;
  const throttled = status === 429;
  const unavailable = status === 400;
  const missing = status === 404;
  const title = throttled
    ? "Please slow down"
    : unavailable
      ? `${noun.charAt(0).toUpperCase()}${noun.slice(1)} are not enabled`
      : missing
        ? "Makerspace not found"
        : `${noun.charAt(0).toUpperCase()}${noun.slice(1)} are unavailable`;
  return (
    <EmptyCard
      tone="error"
      title={title}
      description={throttled ? "Too many requests were made. Wait a moment and retry." : detail ?? error.message}
      action={!missing && !unavailable ? <Button onClick={onRetry}>Retry</Button> : undefined}
    />
  );
}
