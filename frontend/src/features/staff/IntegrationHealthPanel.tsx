import type React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { ApiPath } from "../../generated/api";
import { Button, Card, CardHeader, ErrorText, SkeletonRows, StatTile, StatusChip, Table, TBody, TD, TH, THead, TR, type StatusTone } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { moduleEnabled } from "../../lib/modules";
import type { Makerspace } from "./panels/shared";
import { staffTabPath } from "./staffTabs";

type HealthStatus = "ok" | "warn" | "error" | "unknown";

type SectionHealth = {
  status?: HealthStatus;
  detail?: string;
};

type IntegrationHealth = {
  status: Exclude<HealthStatus, "unknown">;
  email: SectionHealth & {
    total?: number;
    pending?: number;
    sent?: number;
    failed?: number;
    stalled?: number;
    last_failure?: {
      created_at: string;
      subject: string;
      error: string;
      stream: string;
    } | null;
  };
  deliveries_by_stream: SectionHealth & {
    hardware?: string | null;
    printing?: string | null;
  };
  smtp: SectionHealth & { configured?: boolean };
  telegram: SectionHealth & {
    configured?: boolean;
    enabled?: boolean;
    last_sent_at?: string | null;
    last_failure?: { at: string; detail: string } | null;
  };
  worker: SectionHealth & {
    broker_configured?: boolean;
    eager?: boolean;
    last_seen?: string | null;
    stale?: boolean;
  };
};

const integrationHealthPath: ApiPath = "/api/v1/admin/makerspace/{makerspace_id}/integration-health";

export function IntegrationHealthPanel({ makerspace, singleTenantLocked = false }: { makerspace: Makerspace; singleTenantLocked?: boolean }) {
  const health = useQuery({
    queryKey: ["integration-health", makerspace.id],
    queryFn: () =>
      staffRequest<IntegrationHealth>(
        integrationHealthPath
          .replace("/api/v1", "")
          .replace("{makerspace_id}", String(makerspace.id)),
      ),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const data = health.data;
  // The Telegram test alert lives in the Telegram card on this same Settings page.
  const telegramOn = moduleEnabled(makerspace.enabled_modules, "telegram");
  const emailOn = moduleEnabled(makerspace.enabled_modules, "email");
  const printingOn = moduleEnabled(makerspace.enabled_modules, "printing");
  const description = healthDescription(emailOn, telegramOn);

  return (
    <Card as="section" aria-labelledby="integration-health-title">
      <CardHeader
        title={(
          <span id="integration-health-title" className="flex flex-wrap items-center gap-2">
            Integration health
            <StatusChip tone={statusTone(data?.status ?? "unknown")} size="sm">{statusLabel(data?.status)}</StatusChip>
          </span>
        )}
        description={description}
        action={(
          <>
            {emailOn ? (
              <Button asChild variant="secondary" size="sm">
                <Link to={staffTabPath("email-logs", false, makerspace.slug, singleTenantLocked)}>Email log</Link>
              </Button>
            ) : null}
            {telegramOn ? (
              <Button asChild variant="secondary" size="sm">
                <a href="#telegram-settings-title">Telegram test</a>
              </Button>
            ) : null}
          </>
        )}
      />
      <ErrorText message={health.error?.message} />

      {data && emailOn ? (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatTile label="Emails" value={data.email.total ?? 0} />
          <StatTile label="Pending" value={data.email.pending ?? 0} />
          <StatTile label="Sent" value={data.email.sent ?? 0} />
          <StatTile label="Failed" value={data.email.failed ?? 0} tone={(data.email.failed ?? 0) > 0 ? "danger" : "default"} />
          <StatTile label="Stalled" value={data.email.stalled ?? 0} tone={(data.email.stalled ?? 0) > 0 ? "danger" : "default"} />
        </div>
      ) : null}

      <Table label="Integration health">
        <THead>
          <tr>
            <TH>Integration</TH>
            <TH>Status</TH>
            <TH>Details</TH>
          </tr>
        </THead>
        <TBody>
          {health.isLoading ? <SkeletonRows rows={5} cols={3} /> : null}
          {data ? (
            <>
              {emailOn ? <EmailRows data={data} printingOn={printingOn} /> : null}
              {telegramOn ? (
                <HealthRow title="Telegram" section={data.telegram}>
                  <ConfiguredChip configured={data.telegram.configured} />
                  {data.telegram.last_failure ? (
                    <span className="mt-1 block break-words">
                      Last alert failed {relativeTime(data.telegram.last_failure.at)}: {data.telegram.last_failure.detail}
                    </span>
                  ) : data.telegram.last_sent_at ? (
                    <span className="mt-1 block">Last alert sent {relativeTime(data.telegram.last_sent_at)}.</span>
                  ) : null}
                </HealthRow>
              ) : null}
              <HealthRow title="Worker" section={data.worker}>
                <span className={data.worker.stale ? "text-danger-fg" : undefined}>
                  Broker: {data.worker.broker_configured ? "Configured" : "Eager only"} · Eager: {data.worker.eager ? "On" : "Off"} ·
                  Stale: {data.worker.stale ? "Yes" : "No"} · Last seen: {data.worker.last_seen ? relativeTime(data.worker.last_seen) : "Never"}
                </span>
              </HealthRow>
            </>
          ) : null}
        </TBody>
      </Table>
    </Card>
  );
}

function EmailRows({ data, printingOn }: { data: IntegrationHealth; printingOn: boolean }) {
  return (
    <>
      <HealthRow title="Email" section={data.email}>
        {data.email.last_failure ? (
          <>
            <span className="block font-semibold text-ink">{data.email.last_failure.subject || "Last failure"}</span>
            <span className="block text-caption text-ink-muted">
              {data.email.last_failure.stream || "email"} · {relativeTime(data.email.last_failure.created_at)}
            </span>
            <span className="block break-words">{data.email.last_failure.error || "No error detail."}</span>
          </>
        ) : (
          "No failed deliveries."
        )}
      </HealthRow>
      <HealthRow title="Deliveries by stream" section={data.deliveries_by_stream}>
        Hardware: {streamTime(data.deliveries_by_stream.hardware)}
        {printingOn ? <> · Printing: {streamTime(data.deliveries_by_stream.printing)}</> : null}
      </HealthRow>
      <HealthRow title="SMTP" section={data.smtp}>
        {/* No server of its own is normal: mail then goes through the platform sender. */}
        {data.smtp.configured ? <ConfiguredChip configured /> : <StatusChip tone="neutral" size="sm">Platform sender</StatusChip>}
      </HealthRow>
    </>
  );
}

function HealthRow({ title, section, children }: { title: string; section: SectionHealth; children: React.ReactNode }) {
  return (
    <TR>
      <TD className="whitespace-nowrap font-semibold">{title}</TD>
      <TD><StatusChip tone={statusTone(section.status)} size="sm">{statusLabel(section.status)}</StatusChip></TD>
      <TD className="min-w-64 text-ink-secondary">
        {section.detail ? <span className="mb-1 block break-words text-danger-fg">{section.detail}</span> : null}
        {children}
      </TD>
    </TR>
  );
}

function ConfiguredChip({ configured }: { configured?: boolean }) {
  return <StatusChip tone={configured ? "success" : "neutral"} size="sm">{configured ? "Configured" : "Not configured"}</StatusChip>;
}

function healthDescription(emailOn: boolean, telegramOn: boolean) {
  if (emailOn && telegramOn) return "Email, Telegram and background worker status. Refreshes every minute.";
  if (emailOn) return "Email and background worker status. Refreshes every minute.";
  if (telegramOn) return "Telegram and background worker status. Refreshes every minute.";
  return "Background worker status. Refreshes every minute.";
}

function streamTime(value?: string | null) {
  return value ? relativeTime(value) : "never sent";
}

function statusTone(status?: HealthStatus): StatusTone {
  if (status === "ok") return "success";
  if (status === "error") return "danger";
  if (status === "warn" || status === "unknown") return "warning";
  return "neutral";
}

function statusLabel(status?: HealthStatus) {
  if (!status) return "Unknown";
  return status === "ok" ? "OK" : status === "warn" ? "Warning" : status.charAt(0).toUpperCase() + status.slice(1);
}

function relativeTime(value: string) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown";
  const diffMs = timestamp - Date.now();
  const absMs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absMs < hour) return rtf.format(Math.round(diffMs / minute), "minute");
  if (absMs < day) return rtf.format(Math.round(diffMs / hour), "hour");
  if (absMs < 7 * day) return rtf.format(Math.round(diffMs / day), "day");
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
