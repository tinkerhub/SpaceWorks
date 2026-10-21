import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "../../../components/ui";

const DAY_MS = 24 * 60 * 60 * 1000;

/** "2 min ago" / "Yesterday" under seven days, otherwise "13 Oct 2026, 9:30 AM". */
export function formatLogTime(value: string, now = Date.now()) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const diffMs = timestamp - now;
  if (Math.abs(diffMs) >= 7 * DAY_MS) {
    return new Date(timestamp).toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const seconds = Math.round(diffMs / 1000);
  if (Math.abs(seconds) < 60) return "Just now";
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

/** Absolute timestamp for a `title` tooltip next to a relative time. */
export function absoluteTime(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : value;
}

/** Previous / next pager for DRF `next`/`previous` lists of unknown page size. */
export function LogPager({ page, count, hasPrevious, hasNext, onPage, disabled }: {
  page: number;
  count: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onPage: (page: number) => void;
  disabled?: boolean;
}) {
  if (!hasPrevious && !hasNext) {
    return count ? <p className="text-caption text-ink-muted">{count} total</p> : null;
  }
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted">
      <Button size="sm" startIcon={<ChevronLeft />} disabled={disabled || !hasPrevious} onClick={() => onPage(Math.max(1, page - 1))}>
        Previous
      </Button>
      <span className="tabular-nums">Page {page} · {count} total</span>
      <Button size="sm" endIcon={<ChevronRight />} disabled={disabled || !hasNext} onClick={() => onPage(page + 1)}>
        Next
      </Button>
    </nav>
  );
}
