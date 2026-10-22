import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Input, initials } from "../../components/ui";
import { lookupCheckin, type CheckinMatch } from "./api";

type Props = {
  makerspaceSlug: string;
  confirmed: CheckinMatch | null;
  onConfirm: (match: CheckinMatch | null) => void;
  disabled?: boolean;
};

// Why a reason string rather than one generic error: "you are not checked in" is a dead
// end, but "you are checked in, just not as working on a project" is fixable in the
// TinkerHub app in about ten seconds. Collapsing them would cost every one of those
// people their request.
const REASONS: Record<CheckinMatch["reason"], string> = {
  "": "",
  purpose:
    "You are checked in, but not as 'Working on a project'. Change it in the TinkerHub app, then search again.",
  project:
    "You are checked in to work on a project but have not chosen one. Pick your project in the TinkerHub app, then search again.",
  expired: "That check-in session has ended.",
  space: "That check-in is for a different space.",
};

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
  const [name, setName] = useState("");
  const [matches, setMatches] = useState<CheckinMatch[] | null>(null);

  const lookup = useMutation({
    mutationFn: () => lookupCheckin(makerspaceSlug, name.trim()),
    onSuccess: (result) => {
      setMatches(result);
      // Auto-confirm only when the full result has exactly one entry and that entry
      // is eligible. With two people sharing a display name, filtering first would
      // silently file the request against the eligible namesake -- the avatar is the
      // only thing that separates them.
      onConfirm(result.length === 1 && result[0].eligible ? result[0] : null);
    },
  });

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
          disabled={disabled}
          onClick={() => {
            onConfirm(null);
            setMatches(null);
          }}
        >
          Not you?
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="block text-label text-ink" htmlFor="checkin-name">
        Your name, as it appears in TinkerHub
      </label>
      <div className="flex gap-2">
        <Input
          id="checkin-name"
          className="min-w-0 flex-1"
          value={name}
          disabled={disabled}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && name.trim()) {
              event.preventDefault();
              lookup.mutate();
            }
          }}
        />
        <Button
          className="shrink-0"
          disabled={disabled || !name.trim()}
          loading={lookup.isPending}
          loadingLabel="Checking…"
          onClick={() => lookup.mutate()}
        >
          Find me
        </Button>
      </div>

      {lookup.isError ? (
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
                  {match.eligible ? match.project_name : REASONS[match.reason]}
                </p>
              </div>
              <Button size="sm" className="shrink-0" disabled={!match.eligible} onClick={() => onConfirm(match)}>
                That's me
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
