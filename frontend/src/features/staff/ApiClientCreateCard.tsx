import { Button, Card, CardHeader, ErrorBlock, Field, Input, Skeleton, Textarea } from "../../components/ui";
import { ApiClientScopePicker } from "./ApiClientScopePicker";
import type { ApiClientScopeOption } from "./apiClientsApi";
import { splitOrigins } from "./apiClientsApi";

type Props = {
  canManageMakerspace: boolean;
  label: string;
  reason: string;
  origins: string;
  submitted: boolean;
  isPending: boolean;
  error: Error | null;
  scopeOptions: ApiClientScopeOption[];
  scopes: string[];
  scopesLoading: boolean;
  scopesError: Error | null;
  onLabelChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onOriginsChange: (value: string) => void;
  onScopesChange: (value: string[]) => void;
  onSubmit: () => void;
};

const originsPlaceholder = "Allowed browser origins, one per line. Example: https://lab.example.com";

export function ApiClientCreateCard({
  canManageMakerspace,
  label,
  reason,
  origins,
  submitted,
  isPending,
  error,
  scopeOptions,
  scopes,
  scopesLoading,
  scopesError,
  onLabelChange,
  onReasonChange,
  onOriginsChange,
  onScopesChange,
  onSubmit,
}: Props) {
  const originsField = (
    <Field label="Allowed browser origins" helperText="One origin per line, including https://.">
      <Textarea placeholder={originsPlaceholder} value={origins} onChange={(event) => onOriginsChange(event.target.value)} />
    </Field>
  );

  if (canManageMakerspace) {
    const blocked = !label.trim() || !splitOrigins(origins).length || !scopes.length || scopesLoading || !!scopesError || isPending;
    return (
      <Card as="article">
        <CardHeader title="Create API client" description="The client secret is shown once, right after you create the client." />
        <form
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!blocked) onSubmit();
          }}
        >
          <Field label="Client label">
            <Input value={label} onChange={(event) => onLabelChange(event.target.value)} />
          </Field>
          {originsField}
          <div className="grid gap-2">
            <p className="text-label text-ink">Scopes</p>
            <p className="-mt-1 text-caption text-ink-muted">Choose the exact public API access this client needs.</p>
            {scopesLoading ? <Skeleton className="h-24 w-full" /> : null}
            {!scopesLoading && scopeOptions.length ? (
              <ApiClientScopePicker options={scopeOptions} selected={scopes} onChange={onScopesChange} disabled={isPending} />
            ) : null}
            <ErrorBlock error={scopesError} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" disabled={blocked} loading={isPending} loadingLabel="Creating…">
              Create API client
            </Button>
          </div>
          <ErrorBlock error={error} />
        </form>
      </Card>
    );
  }

  const blocked = !label.trim() || !reason.trim() || !splitOrigins(origins).length || isPending;
  return (
    <Card as="article">
      <CardHeader title="Request API access" description="A superadmin reviews the request and shares the key with you securely." />
      <form
        className="grid gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!blocked) onSubmit();
        }}
      >
        <Field label="Request label">
          <Input value={label} onChange={(event) => onLabelChange(event.target.value)} />
        </Field>
        <Field label="Reason for API access">
          <Textarea value={reason} onChange={(event) => onReasonChange(event.target.value)} />
        </Field>
        {originsField}
        <div>
          <Button type="submit" variant="primary" disabled={blocked} loading={isPending} loadingLabel="Submitting…">
            Submit API access request
          </Button>
        </div>
        {submitted ? (
          <p className="text-body-ui text-ink-muted" role="status">
            Request submitted. A superadmin will review and share the key with you securely.
          </p>
        ) : null}
        <ErrorBlock error={error} />
      </form>
    </Card>
  );
}
