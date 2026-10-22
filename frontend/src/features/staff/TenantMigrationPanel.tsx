import { useQuery } from "@tanstack/react-query";

import { Callout, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui";
import { Panel, type Makerspace } from "./panels/shared";
import { TenantMigrationDisclosure } from "./TenantMigrationDisclosure";
import { TenantMigrationExports } from "./TenantMigrationExports";
import { TenantMigrationImports } from "./TenantMigrationImports";
import { TenantMigrationPairings } from "./TenantMigrationPairings";
import {
  getDisclosureClosure,
  listPairings,
  tenantMigrationKeys,
} from "./tenantMigrationApi";
import { ErrorText } from "./tenantMigrationUi";

// Every step keeps its typed receipts and choices while you move between tabs, so the
// panels stay mounted and the inactive ones are only hidden.
const stepClasses = "grid gap-6 data-[state=inactive]:hidden";

export function TenantMigrationPanel({ makerspace }: { makerspace: Makerspace }) {
  const closure = useQuery({
    queryKey: tenantMigrationKeys.closure(makerspace.id),
    queryFn: () => getDisclosureClosure(makerspace.id),
  });
  const pairings = useQuery({
    queryKey: tenantMigrationKeys.pairings,
    queryFn: listPairings,
  });

  return (
    <Panel
      title="Tenant migration"
      description="Move one makerspace from a managed deployment to a self-hosted one. Superadmin only."
    >
      <div className="grid gap-6">
        <Callout tone="danger" title="This is an irreversible workflow">
          Review disclosure, encrypt the export for the target, resolve every identity, verify the
          materialized tenant, then complete the signed two-key cutover. Cutover archives the source
          tenant; it does not delete it. Archives are outside the purge guarantee.
        </Callout>
        <Tabs defaultValue="source">
          <TabsList aria-label="Migration steps">
            <TabsTrigger value="source">Source export</TabsTrigger>
            <TabsTrigger value="pairing">Deployment pairing</TabsTrigger>
            <TabsTrigger value="target">Target import</TabsTrigger>
          </TabsList>
          <TabsContent value="source" forceMount className={stepClasses}>
            <TenantMigrationDisclosure makerspaceId={makerspace.id} />
            <TenantMigrationExports
              makerspaceId={makerspace.id}
              tenantName={makerspace.name}
              closureDigest={closure.data?.digest}
              pairings={pairings.data ?? []}
            />
          </TabsContent>
          <TabsContent value="pairing" forceMount className={stepClasses}>
            {pairings.isLoading ? <Skeleton className="h-24 w-full" /> : null}
            <ErrorText error={pairings.error} />
            <TenantMigrationPairings pairings={pairings.data ?? []} />
          </TabsContent>
          <TabsContent value="target" forceMount className={stepClasses}>
            <TenantMigrationImports pairings={pairings.data ?? []} />
          </TabsContent>
        </Tabs>
      </div>
    </Panel>
  );
}
