import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CalendarArrowDown as CalendarDown, Copy } from "lucide-react";

import { Button, Callout, ConfirmDialog, ErrorText, Input, useToast } from "../../components/ui";
import { memberRequest, memberRequestBlob } from "../../lib/api";

type FeedState = {
  enabled: boolean;
  token_hint: string | null;
  created_at: string | null;
  rotated_at: string | null;
};
type IssuedFeed = { feed_url: string; token_hint: string; created_at: string };

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function MemberCalendarActions({ makerspaceId, makerspaceSlug }: {
  makerspaceId: number; makerspaceSlug: string;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [issuedUrl, setIssuedUrl] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"issue" | "revoke" | null>(null);
  const path = `/member/makerspaces/${makerspaceId}/event-calendar-feed/`;
  const key = ["member", makerspaceSlug, "event-calendar-feed"] as const;
  const feed = useQuery({ queryKey: key, queryFn: () => memberRequest<FeedState>(path) });
  const feedEnabled = Boolean(feed.data?.enabled);
  const download = useMutation({
    mutationFn: async () => downloadBlob(
      await memberRequestBlob(`/member/makerspaces/${makerspaceId}/event-registrations/calendar.ics`),
      "my-events.ics",
    ),
    onError: () => showToast("Calendar not downloaded", { tone: "error" }),
  });
  const issue = useMutation({
    mutationFn: async () => {
      const result = await memberRequest<IssuedFeed>(path, {
        method: "POST", body: JSON.stringify({ confirm_bearer_risk: true }),
      });
      // Keep the bearer URL only in component state. Returning void prevents TanStack's
      // mutation cache from retaining the credential after this one-time reveal.
      setIssuedUrl(result.feed_url);
    },
    onSuccess: async () => {
      showToast(feedEnabled ? "Calendar link replaced" : "Calendar link created", { tone: "success" });
      await queryClient.invalidateQueries({ queryKey: key });
    },
    onError: () => showToast("Calendar link not changed", { tone: "error" }),
  });
  const revoke = useMutation({
    mutationFn: () => memberRequest<void>(path, { method: "DELETE" }),
    onSuccess: async () => {
      setIssuedUrl(null);
      showToast("Calendar link revoked", { tone: "success" });
      await queryClient.invalidateQueries({ queryKey: key });
    },
    onError: () => showToast("Calendar link not revoked", { tone: "error" }),
  });
  const error = feed.error || download.error || issue.error || revoke.error;
  const replacing = feedEnabled;

  return <div className="flex flex-col gap-3 rounded-lg border border-line bg-subtle p-4">
    <div>
      <h3 className="text-label text-ink">My event calendar</h3>
      <p className="mt-0.5 text-caption text-ink-muted">Download your registrations, or subscribe from your calendar app with a private link.</p>
    </div>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" startIcon={<CalendarDown />} loading={download.isPending} loadingLabel="Preparing…" onClick={() => download.mutate()}>
        Download calendar
      </Button>
      <Button size="sm" disabled={issue.isPending || feed.isLoading} onClick={() => setConfirming("issue")}>
        {replacing ? "Rotate subscription link" : "Create subscription link"}
      </Button>
      {replacing ? <Button size="sm" variant="danger" disabled={revoke.isPending} onClick={() => setConfirming("revoke")}>Revoke link…</Button> : null}
    </div>
    {feed.data?.enabled && !issuedUrl ? <p className="text-caption text-ink-muted">
      Active private link ending in <span className="font-mono">{feed.data.token_hint}</span>. The full link is not persisted and cannot be revealed again.
    </p> : null}
    {issuedUrl ? <Callout tone="warning" title="Copy this link now. It will not be shown again.">
      <div className="mt-2 flex flex-col gap-2">
        <Input className="font-mono text-xs" readOnly value={issuedUrl} aria-label="Private calendar subscription link" onFocus={(event) => event.currentTarget.select()} />
        <Button size="sm" className="self-start" startIcon={<Copy />} onClick={() => navigator.clipboard.writeText(issuedUrl).then(() => showToast("Link copied", { tone: "success" }), () => undefined)}>Copy link</Button>
        <p className="text-caption">Treat this URL like a password. Rotate it if it is shared accidentally.</p>
      </div>
    </Callout> : null}
    <ErrorText message={error ? (error instanceof Error ? error.message : "Calendar action failed.") : null} />
    <ConfirmDialog
      open={confirming === "issue"}
      title={replacing ? "Replace your calendar link?" : "Create a calendar link?"}
      message={`This will ${replacing ? "replace" : "create"} a private calendar link. Anyone with the link can see your event schedule.`}
      confirmLabel={replacing ? "Replace link" : "Create link"}
      pending={issue.isPending}
      onCancel={() => setConfirming(null)}
      onConfirm={() => issue.mutate(undefined, { onSettled: () => setConfirming(null) })}
    />
    <ConfirmDialog
      open={confirming === "revoke"}
      title="Revoke your calendar link?"
      message="Revoke the current calendar subscription link? Calendar apps using it stop updating."
      confirmLabel="Revoke link"
      tone="danger"
      pending={revoke.isPending}
      onCancel={() => setConfirming(null)}
      onConfirm={() => revoke.mutate(undefined, { onSettled: () => setConfirming(null) })}
    />
  </div>;
}
