import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  EmptyState,
  ErrorBlock,
  SegmentedControl,
  Skeleton,
  StatusChip,
  useToast,
  type StatusTone,
} from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { staffRequest } from "../../../lib/api";
import { absoluteTime, formatLogTime, LogPager } from "./StaffLogParts";
import { errorText, Panel, useStaffGet, type Makerspace } from "./shared";

type NotificationLevel = "info" | "warning" | "critical";

type NotificationEntry = {
  id: number;
  level: NotificationLevel;
  event: string;
  title: string;
  body: string;
  url_path: string;
  read_at: string | null;
  created_at: string;
};

type NotificationResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: NotificationEntry[];
};

const LEVELS: Record<NotificationLevel, { label: string; tone: StatusTone }> = {
  info: { label: "Info", tone: "info" },
  warning: { label: "Warning", tone: "warning" },
  critical: { label: "Critical", tone: "danger" },
};

export function NotificationInbox({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const params = new URLSearchParams();
  if (unreadOnly) params.set("unread", "true");
  params.set("page", String(page));
  const query = params.toString();
  const notifications = useStaffGet<NotificationResponse>(
    ["notifications", makerspace.id, query],
    `/notifications/makerspace/${makerspace.id}?${query}`,
  );
  const invalidateNotifications = () => {
    queryClient.invalidateQueries({ queryKey: ["notifications", makerspace.id] });
    // The sidebar badge (useUnreadNotifications) caches under this key.
    queryClient.invalidateQueries({ queryKey: ["notifications-unread", makerspace.id] });
  };
  const markRead = useMutation({
    mutationFn: (id: number) =>
      staffRequest<NotificationEntry>(`/notifications/makerspace/${makerspace.id}/${id}/read`, {
        method: "POST",
      }),
    onSuccess: () => {
      invalidateNotifications();
      showToast("Marked as read", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't mark it as read"), { tone: "error" }),
  });
  const markAllRead = useMutation({
    mutationFn: () =>
      staffRequest<{ updated: number }>(`/notifications/makerspace/${makerspace.id}/read-all`, {
        method: "POST",
      }),
    onSuccess: () => {
      invalidateNotifications();
      showToast("All notifications marked as read", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't mark everything as read"), { tone: "error" }),
  });

  const updateUnreadOnly = (checked: boolean) => {
    setUnreadOnly(checked);
    setPage(1);
  };
  const rows = notifications.data?.results ?? [];

  return (
    <Panel
      title="Notifications"
      description="Alerts for this makerspace: overdue loans, machine faults and anything else that needs someone."
      actions={
        <Button
          variant="primary"
          loading={markAllRead.isPending}
          disabled={notifications.data?.count === 0}
          onClick={() => markAllRead.mutate()}
        >
          Mark all read
        </Button>
      }
    >
      <div className="grid gap-4">
        <SegmentedControl
          ariaLabel="Show"
          value={unreadOnly ? "unread" : "all"}
          onValueChange={(value) => updateUnreadOnly(value === "unread")}
          options={[
            { value: "all", label: "All" },
            { value: "unread", label: "Unread only" },
          ]}
          className="self-start justify-self-start"
        />
        <ErrorBlock error={notifications.error} />
        <ErrorBlock error={markRead.error} />
        <ErrorBlock error={markAllRead.error} />

        {notifications.isLoading ? (
          <Card padding="none" aria-busy="true" aria-label="Loading notifications">
            {[0, 1, 2].map((key) => (
              <div key={key} className="grid gap-2 border-b border-line p-4 last:border-b-0">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-full" />
              </div>
            ))}
          </Card>
        ) : null}

        {notifications.data && rows.length === 0 ? (
          <EmptyState
            title={unreadOnly ? "You're all caught up" : "No notifications yet"}
            description={unreadOnly ? "Nothing unread. Switch to All to see earlier alerts." : "Alerts for this makerspace will show up here."}
          />
        ) : null}

        {rows.length ? (
          <Card as="section" padding="none" aria-label="Notification list">
            <ul>
              {rows.map((notification) => {
                const unread = notification.read_at === null;
                const level = LEVELS[notification.level] ?? LEVELS.info;
                return (
                  <li
                    key={notification.id}
                    className={cn("flex flex-wrap items-start gap-3 border-b border-line p-4 last:border-b-0", unread && "bg-subtle")}
                  >
                    <span
                      aria-hidden="true"
                      className={cn("mt-2 size-2 shrink-0 rounded-full", unread ? "bg-accent-ink" : "bg-transparent")}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <StatusChip tone={level.tone} size="sm">{level.label}</StatusChip>
                        {unread ? <span className="sr-only">Unread.</span> : null}
                        {notification.event ? <span className="text-caption text-ink-muted">{humanize(notification.event)}</span> : null}
                        <time className="text-caption text-ink-muted" dateTime={notification.created_at} title={absoluteTime(notification.created_at)}>
                          {formatLogTime(notification.created_at)}
                        </time>
                      </div>
                      <h3 className={cn("break-words text-title", unread ? "text-ink" : "text-ink-secondary")}>{notification.title}</h3>
                      {notification.body ? (
                        <p className="mt-1 whitespace-pre-wrap break-words text-body-ui text-ink-muted">{notification.body}</p>
                      ) : null}
                      {notification.url_path ? (
                        <a className="mt-2 inline-block text-sm font-semibold text-accent-ink underline-offset-4 hover:underline" href={notification.url_path}>
                          Open
                        </a>
                      ) : null}
                    </div>
                    {unread ? (
                      <Button size="sm" variant="secondary" className="shrink-0" disabled={markRead.isPending} onClick={() => markRead.mutate(notification.id)}>
                        Mark read
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </Card>
        ) : null}

        <LogPager
          page={page}
          count={notifications.data?.count ?? 0}
          hasPrevious={Boolean(notifications.data?.previous)}
          hasNext={Boolean(notifications.data?.next)}
          onPage={setPage}
          disabled={notifications.isFetching}
        />
      </div>
    </Panel>
  );
}

function humanize(value: string) {
  const words = value.replace(/[_.]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
