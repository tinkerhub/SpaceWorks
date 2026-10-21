import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { CollaborativeEvent } from "../../generated/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import type { CustomAnswers, CustomFormSchema } from "../forms/customFormTypes";
import { staffRequest } from "../../lib/api";
import { Button, CheckboxField, Chip, ErrorText, useToast } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";

type CollaborativeEventWithPolicy = CollaborativeEvent & {
  registration_requires_approval: boolean;
  effective_registration_cutoff_at: string | null;
  registration_open: boolean;
  series: { public_token: string; title: string } | null;
};

/** Events hosted by makerspaces that have accepted a collaboration with this one.
 *
 * Discovery has its own member-scoped endpoint rather than widening the public event list:
 * that list is `AllowAny` and shared with public registration, so relaxing its `is_public`
 * filter would publish a members-only event to the world. Renders nothing when there is
 * nothing to show, so a space with no partners sees no new section.
 */
export function PartnerEvents({
  makerspaceId,
  slug,
}: {
  makerspaceId: number;
  slug: string;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const events = useQuery({
    queryKey: ["member", slug, "partner-events"],
    queryFn: () => staffRequest<CollaborativeEventWithPolicy[]>(
      `/member/makerspaces/${makerspaceId}/collaborative-events/`,
    ),
    enabled: makerspaceId >= 0,
    retry: false,
  });
  const [openId, setOpenId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  // The accepted waiver's identity, not a bare boolean. A refetch can replace
  // `event.host_waiver` while this form is open, and a lingering `true` would submit
  // acceptance of terms the member never read.
  const [acceptedWaiver, setAcceptedWaiver] = useState<{ id: number; version: string } | null>(null);
  const register = useMutation({
    mutationFn: ({
      eventId, custom_answers, host_waiver_id, host_waiver_version, host_waiver_accepted,
    }: {
      eventId: number;
      custom_answers: CustomAnswers;
      host_waiver_id?: number;
      host_waiver_version?: string;
      host_waiver_accepted?: boolean;
    }) =>
      staffRequest<{ status: string }>(
        `/member/makerspaces/${makerspaceId}/collaborative-events/${eventId}/register/`,
        {
          method: "POST",
          body: JSON.stringify({
            custom_answers, host_waiver_id, host_waiver_version, host_waiver_accepted,
          }),
        },
      ),
    onSuccess: async () => { showToast("Registration sent", { tone: "success" }); await Promise.all([
      // The activity payload carries the new registration and its check-in QR token, so it
      // has to be refetched or the member sees no code for the event they just joined.
      queryClient.invalidateQueries({ queryKey: ["member", slug, "activity"] }),
      queryClient.invalidateQueries({ queryKey: ["member", slug, "partner-events"] }),
    ]); setOpenId(null); setAnswers({}); setAcceptedWaiver(null); },
    onError: () => {
      showToast("Registration not sent", { tone: "error" });
      // A rejection is usually the host having published new terms since this list loaded.
      // Without refetching, the component would keep showing and resubmitting the
      // superseded version on every retry until the user reloaded the page.
      queryClient.invalidateQueries({ queryKey: ["member", slug, "partner-events"] });
      setAcceptedWaiver(null);
    },
  });

  const rows = events.data ?? [];
  const groups = rows.reduce<Array<{
    key: string; title: string | null; events: CollaborativeEventWithPolicy[];
  }>>((result, event) => {
    const key = event.series?.public_token ?? `event-${event.id}`;
    const group = result.find((candidate) => candidate.key === key);
    if (group) group.events.push(event);
    else result.push({ key, title: event.series?.title ?? null, events: [event] });
    return result;
  }, []);
  if (!rows.length) return null;

  return (
    <AccountCard
      title="Events at partner makerspaces"
      description="Your makerspace collaborates with these hosts, so you can register even when the event is not listed publicly."
    >
      <div className="flex flex-col gap-5">
        {groups.map((group) => <section key={group.key} aria-label={group.title ?? undefined} className="flex flex-col gap-2">
          {group.title ? <div className="flex flex-wrap items-center gap-2"><h3 className="text-label text-ink">{group.title}</h3><Chip size="sm" tone="secondary">Series</Chip></div> : null}
          <ul className="divide-y divide-line rounded-lg border border-line">{group.events.map((event) => {
          // A host may attach a custom form, and the backend validates required answers.
          // Without rendering those fields the button would post `{}` and such an event
          // would simply be unregisterable through this surface.
          const schema = (event.custom_form ?? null) as CustomFormSchema | null;
          const needsAnswers = Boolean(schema?.length);
          // The HOST's waiver, not this member's own space's. They are walking into
          // somebody else's premises, and there is no membership at the host to carry the
          // acceptance, so it is recorded on the registration instead.
          // Host-owned rows carry a waiver too, but the caller's own membership already
          // holds that acceptance and the POST path deliberately exempts them -- asking
          // again would be a second, meaningless agreement.
          const waiver = event.host_slug === slug ? null : event.host_waiver;
          const open = openId === event.id;
          const mustExpand = needsAnswers || Boolean(waiver);
          const blocked = Boolean(waiver) && !(
            acceptedWaiver
            && acceptedWaiver.id === waiver?.id
            && acceptedWaiver.version === waiver?.version
          );
          const Title = group.title ? "h4" : "h3";
          return (
            <li key={event.id} className="flex flex-col gap-3 px-4 py-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <Title className="font-semibold text-ink">{event.title}</Title>
                  <p className="mt-0.5 text-caption text-ink-muted">
                    Hosted by {event.host_name} · <span className="font-mono">{new Date(event.starts_at).toLocaleString()}</span>
                  </p>
                </div>
                <Button
                  size="sm"
                  variant={open ? "primary" : "secondary"}
                  className="self-start sm:self-auto"
                  disabled={!event.registration_open || register.isPending || (open && blocked)}
                  loading={register.isPending && register.variables?.eventId === event.id}
                  onClick={() => {
                    if (mustExpand && !open) {
                      setAnswers({});
                      setAcceptedWaiver(null);
                      setOpenId(event.id);
                      return;
                    }
                    register.mutate({
                      eventId: event.id,
                      custom_answers: open ? answers : {},
                      host_waiver_id: waiver?.id,
                      host_waiver_version: waiver?.version,
                      host_waiver_accepted: Boolean(waiver) && !blocked,
                    });
                  }}
                >
                  {!event.registration_open ? "Registration closed" : mustExpand && !open ? `${event.registration_requires_approval ? "Apply" : "Register"}…` : event.registration_requires_approval ? "Apply" : "Register"}
                </Button>
              </div>
              {!event.registration_open && event.effective_registration_cutoff_at ? <p className="text-caption text-ink-muted">Closed at {new Date(event.effective_registration_cutoff_at).toLocaleString()}</p> : null}
              {/* Unmounted when closed rather than hidden, so keyboard users cannot tab
                  into fields for an event they are not registering for. */}
              {open && waiver ? (
                <div className="flex flex-col gap-2">
                  <h4 className="text-label text-ink">
                    {event.host_name}&apos;s waiver (version {waiver.version})
                  </h4>
                  <div className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-subtle p-3 text-body-ui text-ink-secondary">
                    {waiver.body}
                  </div>
                  <CheckboxField
                    checked={!blocked}
                    onCheckedChange={(checked) => setAcceptedWaiver(
                      checked === true && waiver
                        ? { id: waiver.id, version: waiver.version }
                        : null,
                    )}
                    label={<>I accept {event.host_name}&apos;s waiver</>}
                  />
                </div>
              ) : null}
              {open && schema ? (
                <CustomFormFields schema={schema} answers={answers} onChange={setAnswers} />
              ) : null}
            </li>
          );
        })}</ul></section>)}
        <ErrorText message={register.error ? (register.error instanceof Error ? register.error.message : "Could not register.") : null} />
      </div>
    </AccountCard>
  );
}
