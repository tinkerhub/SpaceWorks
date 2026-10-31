import { useLayoutEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Input, initials } from "../../components/ui";
import { lookupCheckin, type CheckinMatch } from "./api";
import { useCheckinProvider } from "./useCheckinProvider";

type Props = {
  makerspaceSlug: string;
  confirmed: CheckinMatch | null;
  onConfirm: (match: CheckinMatch | null) => void;
  disabled?: boolean;
};

type Context = { slug: string; generation: number };
type Lookup = {
  context: Context;
  slug: string;
  name: string;
  generation: number;
  lifetime: symbol;
};
type View = {
  context: Context;
  name: string;
  matches: CheckinMatch[] | null;
  error: boolean;
  pending: boolean;
};
const emptyView = (context: Context): View => ({ context, name: "", matches: null, error: false, pending: false });

/** Each lookup belongs to one tenant visit, typed intent and mounted lifetime. */
function useCheckinLookup(
  slug: string,
  disabled: boolean | undefined,
  onConfirm: (match: CheckinMatch | null) => void,
) {
  const contextRef = useRef<Context>({ slug, generation: 0 });
  const active = useRef<Lookup | null>(null);
  const lifetime = useRef<symbol | null>(null);
  if (contextRef.current.slug !== slug) {
    contextRef.current = { slug, generation: 0 };
    active.current = null;
  }
  const context = contextRef.current;
  const latest = useRef({ disabled, onConfirm });
  latest.current = { disabled, onConfirm };
  const [stored, setView] = useState<View>(() => emptyView(context));
  // An effect reset would expose the previous tenant's name/results for one render.
  const view = stored.context === context ? stored : emptyView(context);
  const generation = context.generation;

  useLayoutEffect(() => {
    const mountedLifetime = Symbol();
    lifetime.current = mountedLifetime;
    setView((current) => current.pending ? { ...current, pending: false } : current);
    return () => {
      if (lifetime.current === mountedLifetime) {
        lifetime.current = null;
        active.current = null;
      }
    };
  }, []);

  function isCurrent(input: Lookup) {
    return active.current === input && lifetime.current === input.lifetime &&
      contextRef.current === input.context && input.context.generation === input.generation;
  }

  const mutation = useMutation({
    mutationFn: (input: Lookup) => {
      if (!isCurrent(input) || latest.current.disabled) throw new Error("Check-in lookup is no longer current.");
      return lookupCheckin(input.slug, input.name);
    },
    onSuccess: (matches, input) => {
      if (!isCurrent(input) || latest.current.disabled) return;
      setView((current) => ({ ...current, matches, error: false }));
      // Examine the full result: eligible namesakes must never be silently preferred.
      latest.current.onConfirm(matches.length === 1 && matches[0].eligible ? matches[0] : null);
    },
    onError: (_error, input) => {
      if (!isCurrent(input) || latest.current.disabled) return;
      setView((current) => ({ ...current, error: true }));
    },
    onSettled: (_data, _error, input) => {
      // Disabled blocks acceptance, but must not leave this lookup's input locked.
      if (!isCurrent(input)) return;
      active.current = null;
      setView((current) => current.context === input.context ? { ...current, pending: false } : current);
    },
  });

  function canInteract() {
    return lifetime.current !== null && contextRef.current === context &&
      context.generation === generation && !latest.current.disabled && !active.current;
  }

  function edit(name: string) {
    if (!canInteract()) return;
    const next = { slug, generation: generation + 1 };
    contextRef.current = next;
    setView({ ...emptyView(next), name });
    latest.current.onConfirm(null);
  }

  function lookup() {
    if (!canInteract() || !view.name.trim() || !lifetime.current) return;
    const input: Lookup = {
      context, slug, name: view.name.trim(), generation, lifetime: lifetime.current,
    };
    active.current = input;
    setView({ ...view, matches: null, error: false, pending: true });
    mutation.mutate(input);
  }

  function select(match: CheckinMatch) {
    if (canInteract() && match.eligible && view.matches?.includes(match)) {
      latest.current.onConfirm(match);
    }
  }

  return { ...view, edit, lookup, select };
}

// Why a reason string rather than one generic error: "you are not checked in" is a dead
// end, but "you are checked in, just not for the required purpose" is fixable in the
// check-in app in about ten seconds. Collapsing them would cost every one of those
// people their request.
function reasonText(reason: CheckinMatch["reason"], purpose: string, app: string): string {
  switch (reason) {
    case "purpose":
      return `You are checked in, but not as '${purpose}'. Change it in ${app}, then search again.`;
    case "project":
      return `You are checked in but have not chosen a project. Pick your project in ${app}, then search again.`;
    case "expired":
      return "That check-in session has ended.";
    case "space":
      return "That check-in is for a different space.";
    default:
      return "";
  }
}

/** Decorative: the name is always printed beside it. */
function Face({ name, src, className }: { name: string; src: string; className: string }) {
  return src ? (
    <img src={src} alt="" className={`${className} shrink-0 rounded-full object-cover`} />
  ) : (
    <span aria-hidden="true" className={`${className} inline-flex shrink-0 items-center justify-center rounded-full bg-emphasis text-xs font-bold text-ink-secondary`}>
      {initials(name)}
    </span>
  );
}

export function CheckinIdentityStep({
  makerspaceSlug,
  confirmed,
  onConfirm,
  disabled,
}: Props) {
  const checkin = useCheckinProvider(makerspaceSlug);
  const lookup = useCheckinLookup(makerspaceSlug, disabled, onConfirm);
  const { name, matches, pending } = lookup;

  if (confirmed) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-success-bg p-3 text-success-fg">
        <Face name={confirmed.name} src={confirmed.avatar} className="size-10" />
        <div className="min-w-0 flex-1">
          <p className="break-words text-label">{confirmed.name}</p>
          <p className="break-words text-caption opacity-90">{confirmed.project_name}</p>
        </div>
        <Button
          variant="quiet"
          size="sm"
          className="shrink-0 text-success-fg hover:text-success-fg"
          disabled={disabled || pending}
          onClick={() => lookup.edit(name)}
        >
          Not you?
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="block text-label text-ink" htmlFor="checkin-name">
        Your name, as it appears {checkin.appearsIn}
      </label>
      <div className="flex gap-2">
        <Input
          id="checkin-name"
          className="min-w-0 flex-1"
          value={name}
          disabled={disabled || pending}
          onChange={(event) => lookup.edit(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              lookup.lookup();
            }
          }}
        />
        <Button
          className="shrink-0"
          disabled={disabled || pending || !name.trim()}
          loading={pending}
          loadingLabel="Checking…"
          onClick={lookup.lookup}
        >
          Find me
        </Button>
      </div>

      {lookup.error ? (
        <p role="alert" className="text-caption text-danger-fg">
          We could not check the check-in list just now. Please try again.
        </p>
      ) : null}

      {matches !== null && matches.length === 0 ? (
        <p role="alert" className="text-caption text-danger-fg">
          No one is checked in under that name right now. Check the spelling, or check
          in first.
        </p>
      ) : null}

      {matches && matches.length > 0 ? (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {matches.map((match) => (
            <li key={match.mid} className="flex items-center gap-3 p-2.5">
              <Face name={match.name} src={match.avatar} className="size-9" />
              <div className="min-w-0 flex-1">
                <p className="break-words text-body-ui text-ink">{match.name}</p>
                <p className="break-words text-caption text-ink-muted">
                  {match.eligible ? match.project_name : reasonText(match.reason, checkin.purpose, checkin.app)}
                </p>
              </div>
              <Button size="sm" className="shrink-0" disabled={disabled || pending || !match.eligible} onClick={() => lookup.select(match)}>
                That's me
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
