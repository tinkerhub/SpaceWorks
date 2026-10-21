import { Card, CardHeader } from "../../components/ui";
import { type Makerspace } from "./StaffPanels";

type ApiSettingsSummary = {
  public_code: string;
  cors_allowed_origins: string[];
};

export function ApiClientsAccessSummary({
  makerspace,
  isSuperadmin,
  settings,
}: {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  settings?: ApiSettingsSummary;
}) {
  const origins = isSuperadmin
    ? (settings?.cors_allowed_origins ?? []).join(", ") || "No active client origins"
    : "Managed by superadmin";
  return (
    <Card as="section">
      <CardHeader title="Makerspace API access" description="What other systems use to reach this makerspace." />
      <dl className="grid gap-4 sm:grid-cols-2">
        <Config label="Makerspace code" value={settings?.public_code ?? makerspace.public_code} mono />
        <Config label="Allowed browser origins" value={origins} mono={isSuperadmin && Boolean(settings?.cors_allowed_origins.length)} />
      </dl>
    </Card>
  );
}

function Config({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-label text-ink-secondary">{label}</dt>
      <dd className={mono ? "mt-1 break-all font-mono text-sm text-ink" : "mt-1 text-body-ui text-ink"}>{value}</dd>
    </div>
  );
}
