import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Callout,
  Card,
  CardHeader,
  Checkbox,
  ErrorBlock,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  useToast,
} from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { NotificationChannelPreferences } from "./NotificationChannelPreferences";
import type {
  MuteChange,
  NotificationFeature,
  NotificationRulesResponse,
  RuleCatalogEntry,
  RuleMute,
} from "./notificationRuleTypes";

/** Channel switches per feature, then the advanced per-recipient email mutes. */
export function NotificationMuteMatrix({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const path = `/admin/makerspace/${makerspaceId}/notification-rules`;
  const queryKey = ["notification-rules", makerspaceId] as const;

  const rules = useQuery({
    queryKey,
    queryFn: () => staffRequest<NotificationRulesResponse>(path),
  });

  const updateMute = useMutation({
    mutationFn: (change: MuteChange) =>
      staffRequest<NotificationRulesResponse>(path, {
        method: "PATCH",
        body: JSON.stringify({ changes: [change] }),
      }),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<NotificationRulesResponse>(queryKey);
      queryClient.setQueryData<NotificationRulesResponse>(queryKey, (current) =>
        current ? { ...current, mutes: applyMuteChange(current.mutes, change) } : current,
      );
      return { previous };
    },
    onSuccess: (_data, change) => showToast(change.muted ? "Email muted" : "Email unmuted", { tone: "success" }),
    onError: (error, _change, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous);
      }
      showToast(error.message || "Couldn't save the mute", { tone: "error" });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  if (rules.isLoading) {
    return (
      <Card aria-busy="true" aria-label="Loading notification rules">
        <Skeleton className="mb-4 h-6 w-48" />
        <Skeleton className="h-40 w-full" />
      </Card>
    );
  }

  if (rules.error) {
    return (
      <Callout tone="danger" role="alert" title="Couldn't load notification rules">
        {rules.error.message}
      </Callout>
    );
  }

  if (!rules.data) return null;
  const data = rules.data;

  return (
    <div className="grid min-w-0 gap-4">
      <NotificationChannelPreferences makerspaceId={makerspaceId} rules={data} />
      <Card as="section" aria-labelledby="advanced-email-mutes-heading">
        <CardHeader
          title={<span id="advanced-email-mutes-heading">Advanced email mutes</span>}
          description="Tick a box to mute that email for one recipient group and event. Mutes apply only while the feature's Email channel is on. Return reminders can't be muted."
        />
        <div className="grid min-w-0 gap-5">
          {data.catalog.map((entry) => {
            const emailEnabled = isEmailEnabled(entry, data);
            const disabledMessageId = `email-disabled-${entry.stream}-${entry.audience}`;
            return (
              <section key={`${entry.stream}:${entry.audience}`} className="grid min-w-0 gap-2">
                <h3 className="text-label text-ink">
                  {streamLabel(entry.stream)} &middot; {audienceLabel(entry.audience)}
                </h3>
                {!emailEnabled ? (
                  <p id={disabledMessageId} className="text-caption text-warning-fg">
                    Read-only while this feature&apos;s Email channel is off.
                  </p>
                ) : null}
                <Table label={`${streamLabel(entry.stream)} ${audienceLabel(entry.audience)} mutes`}>
                  <caption className="sr-only">
                    Ticked boxes mute emails for {streamLabel(entry.stream)} {audienceLabel(entry.audience)}.
                  </caption>
                  <THead>
                    <tr>
                      <TH>Recipients</TH>
                      {entry.events.map((eventName) => (
                        <TH key={eventName} className="min-w-28 max-w-40 whitespace-normal text-center leading-snug">
                          {humanize(eventName)}
                        </TH>
                      ))}
                    </tr>
                  </THead>
                  <TBody>
                    {entry.targets.map((target) => (
                      <TR key={target}>
                        <TH scope="row" className="text-label text-ink">{targetLabel(target)}</TH>
                        {entry.events.map((eventName) => {
                          const checked = isMuted(data.mutes, {
                            target,
                            stream: entry.stream,
                            event: eventName,
                            audience: entry.audience,
                          });
                          return (
                            <TD key={eventName} className="text-center">
                              <Checkbox
                                aria-describedby={!emailEnabled ? disabledMessageId : undefined}
                                aria-label={`${checked ? "Unmute" : "Mute"} ${targetLabel(target)} ${humanize(eventName)}`}
                                checked={checked}
                                disabled={updateMute.isPending || !emailEnabled}
                                onCheckedChange={(next) =>
                                  updateMute.mutate({
                                    target,
                                    stream: entry.stream,
                                    event: eventName,
                                    audience: entry.audience,
                                    muted: next === true,
                                  })
                                }
                              />
                            </TD>
                          );
                        })}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </section>
            );
          })}
        </div>
        <ErrorBlock error={updateMute.error} className="mt-3" />
      </Card>
    </div>
  );
}

function isEmailEnabled(entry: RuleCatalogEntry, rules: NotificationRulesResponse) {
  const feature = featureForEntry(entry, rules.features);
  if (!feature) return true;
  return (
    rules.preferences.find(
      (cell) => cell.feature === feature.key && cell.channel === "email",
    )?.enabled ?? true
  );
}

function featureForEntry(entry: RuleCatalogEntry, features: NotificationFeature[]) {
  const aliases: Record<string, string> = {
    hardware: "hardware_requests",
    hardware_request: "hardware_requests",
    hardware_requests: "hardware_requests",
    print: "printing",
    printing: "printing",
  };
  const expectedKey = aliases[entry.stream] ?? entry.stream;
  return (
    features.find((feature) => feature.key === expectedKey) ??
    features.find((feature) =>
      entry.events.some((eventName) => feature.events.includes(eventName)),
    )
  );
}

function applyMuteChange(mutes: RuleMute[], change: MuteChange) {
  const withoutCurrent = mutes.filter((mute) => !matchesMute(mute, change));
  return change.muted ? [...withoutCurrent, change] : withoutCurrent;
}

function isMuted(mutes: RuleMute[], candidate: RuleMute) {
  return mutes.some((mute) => matchesMute(mute, candidate));
}

function matchesMute(mute: RuleMute, candidate: RuleMute) {
  return (
    mute.target === candidate.target &&
    mute.stream === candidate.stream &&
    mute.event === candidate.event &&
    mute.audience === candidate.audience
  );
}

function streamLabel(stream: string) {
  return humanize(stream);
}

function audienceLabel(audience: string) {
  if (audience === "requester") return "Requester emails";
  if (audience === "staff") return "Staff emails";
  return `${humanize(audience)} emails`;
}

function targetLabel(target: string) {
  return (
    {
      requester: "Requesters",
      space_manager: "Space managers",
      inventory_manager: "Inventory managers",
      machine_manager: "Machine managers",
    }[target] ?? humanize(target)
  );
}

function humanize(value: string) {
  const label = value.replace(/_/g, " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}
