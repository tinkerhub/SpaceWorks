import { StatusChip, TD, TR } from "../../components/ui";
import { moduleEnabled } from "../../lib/modules";

type ChatChannel = "telegram" | "slack" | "mattermost" | "discord";
type Destination = {
  id: number;
  channel: ChatChannel;
  label: string;
  is_active: boolean;
  configured: boolean;
  last_sent_at: string | null;
  failed: number;
  last_failure: { at: string; error: string } | null;
};

export type ChatDestinationsHealth = {
  status?: "ok" | "warn" | "error" | "unknown";
  detail?: string;
  destinations?: Destination[];
  legacy_channels?: Partial<Record<ChatChannel, boolean>>;
};

const CHANNELS: Record<ChatChannel, string> = {
  telegram: "Telegram", slack: "Slack", mattermost: "Mattermost", discord: "Discord",
};

export function ChatDestinationRows({ section, enabledModules, relativeTime }: {
  section?: ChatDestinationsHealth;
  enabledModules?: string[];
  relativeTime: (value: string) => string;
}) {
  const channels = (Object.keys(CHANNELS) as ChatChannel[])
    .filter((channel) => moduleEnabled(enabledModules, channel));
  if (!channels.length) return null;
  const destinations = (section?.destinations ?? [])
    .filter((destination) => channels.includes(destination.channel));
  const status = section?.status ?? "unknown";
  const unavailable = status === "unknown";

  return (
    <>
      <TR>
        <TD className="whitespace-nowrap font-semibold">Chat destinations</TD>
        <TD>
          <StatusChip tone={unavailable ? "warning" : status === "error" ? "danger" : status === "warn" ? "warning" : "success"} size="sm">
            {unavailable ? "Unknown" : status === "ok" ? "OK" : status === "error" ? "Error" : "Warning"}
          </StatusChip>
        </TD>
        <TD className="min-w-64 break-words text-ink-secondary">
          {section?.detail || (unavailable ? "Destination health is unavailable." : `${destinations.length} destinations for enabled channels.`)}
        </TD>
      </TR>
      {destinations.map((destination) => (
        <TR key={destination.id}>
          <TD className="font-semibold">
            {destination.label}
            <span className="block text-caption font-normal text-ink-muted">{CHANNELS[destination.channel]} destination</span>
          </TD>
          <TD>
            <StatusChip tone={destination.is_active ? "success" : "neutral"} size="sm">
              {destination.is_active ? "Active" : "Disabled"}
            </StatusChip>
          </TD>
          <TD className="min-w-64 text-ink-secondary">
            <Configuration configured={destination.configured} />
            <span className={destination.failed > 0 ? "mt-1 block text-danger-fg" : "mt-1 block"}>
              Failed deliveries: {destination.failed}
            </span>
            <span className="block">Last delivery: {destination.last_sent_at ? relativeTime(destination.last_sent_at) : "Never"}</span>
            {destination.last_failure ? (
              <span className="block break-words text-danger-fg">
                Last failure {relativeTime(destination.last_failure.at)}: {destination.last_failure.error}
              </span>
            ) : null}
          </TD>
        </TR>
      ))}
      {channels.map((channel) => {
        const configured = section?.legacy_channels?.[channel];
        if (configured === undefined) return null;
        return (
          <TR key={`legacy-${channel}`}>
            <TD className="font-semibold">{CHANNELS[channel]} legacy channel</TD>
            <TD><Configuration configured={configured} /></TD>
            <TD className="text-ink-secondary">Uses the makerspace integration settings.</TD>
          </TR>
        );
      })}
    </>
  );
}

function Configuration({ configured }: { configured: boolean }) {
  return <StatusChip tone={configured ? "success" : "neutral"} size="sm">{configured ? "Configured" : "Not configured"}</StatusChip>;
}
