import { ChevronRight } from "lucide-react";

import { Button, Callout, Chip, Loader } from "../../components/ui";
import type { Makerspace } from "./StaffPanels";

export type MakerspaceChoicesProps = {
  makerspaces: Makerspace[];
  loading: boolean;
  error?: boolean;
  onRetry?: () => void;
  onSelect: (id: number) => void;
};

/** Only rows returned by the session's allowed-makerspace query may be chosen. */
export function MakerspaceChoices({ makerspaces, loading, error, onRetry, onSelect }: MakerspaceChoicesProps) {
  if (loading) return <div className="flex justify-center py-10"><Loader label="Loading makerspaces" /></div>;
  if (error) return (
    <Callout tone="warning">
      <p>Could not check makerspace access. Retry to load the spaces available to this account from this site.</p>
      <Button variant="secondary" className="mt-3" onClick={onRetry}>Retry makerspaces</Button>
    </Callout>
  );
  if (!makerspaces.length) return <Callout tone="warning">No makerspaces available to this account from this site.</Callout>;
  return (
    <>
      <p className="mb-4 text-body-ui text-ink-muted">Only makerspaces allowed for this account and site are listed.</p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {makerspaces.map((makerspace) => (
          <li key={makerspace.id} className="min-w-0">
            <button
              type="button"
              onClick={() => onSelect(makerspace.id)}
              className="group flex h-full w-full min-w-0 items-center gap-3 rounded-lg border border-line bg-canvas p-4 text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="max-w-full break-all font-mono text-caption text-ink-muted">{makerspace.public_code ?? makerspace.slug}</span>
                <span className="max-w-full break-words text-title text-ink">{makerspace.name}</span>
                {makerspace.superadmin_access_enabled === false ? (
                  <span className="mt-1"><Chip size="sm" tone="warning">Superadmin access: Off</Chip></span>
                ) : null}
                <span className="sr-only">Operate this makerspace</span>
              </span>
              <ChevronRight aria-hidden="true" className="size-5 shrink-0 text-ink-muted transition-transform duration-180 ease-standard group-hover:translate-x-0.5" />
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
