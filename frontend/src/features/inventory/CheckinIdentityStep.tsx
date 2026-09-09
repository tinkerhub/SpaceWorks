import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

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
      <div className="flex items-center gap-3 rounded-md border border-emerald-300 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950">
        {confirmed.avatar ? (
          <img
            src={confirmed.avatar}
            alt=""
            className="h-10 w-10 shrink-0 rounded-full object-cover"
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{confirmed.name}</p>
          <p className="truncate text-xs text-slate-600 dark:text-slate-400">
            {confirmed.project_name}
          </p>
        </div>
        <button
          type="button"
          className="shrink-0 text-xs underline disabled:opacity-40"
          disabled={disabled}
          onClick={() => {
            onConfirm(null);
            setMatches(null);
          }}
        >
          Not you?
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium" htmlFor="checkin-name">
        Your name, as it appears in TinkerHub
      </label>
      <div className="flex gap-2">
        <input
          id="checkin-name"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
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
        <button
          type="button"
          className="rounded-md bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          disabled={disabled || !name.trim() || lookup.isPending}
          onClick={() => lookup.mutate()}
        >
          {lookup.isPending ? "Checking…" : "Find me"}
        </button>
      </div>

      {lookup.isError ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          We could not check the check-in list just now. Please try again.
        </p>
      ) : null}

      {matches !== null && matches.length === 0 ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          No one is checked in under that name right now. Check the spelling, or check
          in first.
        </p>
      ) : null}

      {matches && matches.length > 0 ? (
        <ul className="space-y-2">
          {matches.map((match) => (
            <li
              key={match.mid}
              className="flex items-center gap-3 rounded-md border border-slate-200 p-2 dark:border-slate-800"
            >
              {match.avatar ? (
                <img
                  src={match.avatar}
                  alt=""
                  className="h-9 w-9 shrink-0 rounded-full object-cover"
                />
              ) : null}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{match.name}</p>
                <p className="truncate text-xs text-slate-600 dark:text-slate-400">
                  {match.eligible ? match.project_name : REASONS[match.reason]}
                </p>
              </div>
              <button
                type="button"
                className="shrink-0 rounded-md border border-slate-300 px-2 py-1 text-xs disabled:opacity-40 dark:border-slate-700"
                disabled={!match.eligible}
                onClick={() => onConfirm(match)}
              >
                That's me
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
