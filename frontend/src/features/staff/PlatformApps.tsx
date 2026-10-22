import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { SkipLink } from "../../components/SkipLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Button, Card, Chip, ErrorText, Field, Input, PageHeader, SectionHeading, buttonClasses } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { qrResolveErrorText } from "./evidenceUi";
import { PublicInventoryPage } from "../inventory/PublicInventoryPage";
import { StaffApp } from "./StaffApp";

type ResolveResult = {
  target: Record<string, string | number>;
  allowed_actions: string[];
};

export function KioskPage() {
  const { slug } = useParams();
  return (
    // PublicInventoryPage brings its own main landmark and skip link; this only adds the kiosk bar.
    <div className="min-h-dvh bg-subtle text-ink">
      <header className="border-b border-line bg-canvas">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <SpaceWorksBadge />
            <div className="min-w-0 border-l border-line pl-4">
              <p className="text-caption text-ink-muted">Kiosk</p>
              <h1 className="text-h4 text-ink">Public desk</h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link className={buttonClasses({ variant: "secondary", size: "sm" })} to={`/m/${slug ?? ""}`}>
              Catalog
            </Link>
          </div>
        </div>
      </header>
      <PublicInventoryPage />
    </div>
  );
}

export function ScannerPage() {
  const [payload, setPayload] = useState("");
  const resolve = useMutation({
    mutationFn: () =>
      staffRequest<ResolveResult>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: payload.trim() }),
      }),
  });
  return (
    <div className="flex min-h-dvh flex-col bg-subtle text-ink">
      <SkipLink />
      <header className="flex items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <SpaceWorksBadge />
        <ThemeToggle />
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-12 pt-6 sm:px-6">
        <PageHeader kicker="Scanner" title="QR resolution" description="Scan or paste a QR payload to see what it points to and what you can do with it." />
        <Card>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              if (payload.trim() && !resolve.isPending) resolve.mutate();
            }}
          >
            <Field className="flex-1" label="QR payload">
              <Input
                className="font-mono"
                placeholder="Scan or paste QR payload"
                value={payload}
                onChange={(event) => setPayload(event.target.value)}
              />
            </Field>
            <Button variant="primary" type="submit" disabled={!payload.trim()} loading={resolve.isPending}>
              Resolve
            </Button>
          </form>
          {resolve.isError ? <div className="mt-4"><ErrorText message={qrResolveErrorText(resolve.error, "Could not resolve that QR code.")} /></div> : null}
          {resolve.data ? (
            <div className="mt-6 grid gap-4 border-t border-line pt-5">
              <SectionHeading as="h2" title="Target" />
              <pre className="overflow-auto rounded-md border border-line bg-subtle p-3 font-mono text-xs text-ink-secondary">
                {JSON.stringify(resolve.data.target, null, 2)}
              </pre>
              <SectionHeading as="h2" title="Allowed actions" />
              <div className="flex flex-wrap gap-2">
                {resolve.data.allowed_actions.map((action) => (
                  <Chip key={action} tone="neutral" className="font-mono">{action}</Chip>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      </main>
    </div>
  );
}

export function SuperadminPage() {
  return <StaffApp />;
}
