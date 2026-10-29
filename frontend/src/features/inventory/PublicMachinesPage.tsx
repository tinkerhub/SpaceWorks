import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { CollapsibleSection, EmptyState, PageHeader, Skeleton, StatusBadge, buttonClasses } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useModules } from "../../lib/modules";
import { PublicLoadError } from "./PublicInventoryParts";
import { useMakerspacePublic } from "./useMakerspacePublic";
import { serviceRequestPath } from "../machineService/publicApi";
import { useServiceTypes } from "../machineService/useServiceTypes";

type PublicMachine = {
  name: string;
  machine_type: { id: number; name: string; icon: string };
  image_url: string | null;
  status: "idle" | "running" | "reserved" | "maintenance" | "offline";
  usage_hours: string;
};

type PaginatedMachines = {
  count: number;
  next: string | null;
  previous: string | null;
  results: PublicMachine[];
};

const PUBLIC_MACHINES_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/machines";

function publicMachinesPath(slug: string) {
  return PUBLIC_MACHINES_PATH.replace("/api/v1", "").replace(
    "{makerspace_slug}", encodeURIComponent(slug),
  );
}

export function PublicMachinesPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug } = space;
  const { moduleEnabled } = useModules();
  const serviceEnabled = moduleEnabled("machines") && moduleEnabled("machine_service");
  const serviceTypes = useServiceTypes(makerspaceSlug, serviceEnabled);
  const requestableIds = new Set((serviceEnabled ? serviceTypes.data ?? [] : [])
    .filter((type) => !type.is_printer || moduleEnabled("printing")).map((type) => type.id));
  const machines = useQuery({
    queryKey: ["public-machines", makerspaceSlug],
    // Grouped by type on one page, so every DRF page is fetched rather than paged through.
    queryFn: async () => {
      const all: PublicMachine[] = [];
      for (let page = 1; ; page += 1) {
        const data = await tenantPublicRequest<PaginatedMachines>(
          makerspaceSlug, `${publicMachinesPath(makerspaceSlug)}?page=${page}`,
        );
        all.push(...data.results);
        if (!data.next) return all;
      }
    },
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });

  const groups = useMemo(() => {
    const byType = new Map<number, { name: string; icon: string; machines: PublicMachine[] }>();
    for (const machine of machines.data ?? []) {
      const key = machine.machine_type.id;
      const existing = byType.get(key);
      if (existing) existing.machines.push(machine);
      else byType.set(key, { name: machine.machine_type.name, icon: machine.machine_type.icon, machines: [machine] });
    }
    return [...byType.entries()].map(([id, group]) => ({ id, ...group }));
  }, [machines.data]);

  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const toggleGroup = (id: number) => setCollapsed((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Machines" />}>
      <PublicContainer>
        <PageHeader kicker="Our machines" title="Machines" description="Equipment available in this makerspace, grouped by kind." />
        {serviceEnabled ? <div className="mt-5"><Link className={buttonClasses({ variant: "secondary" })} to={serviceRequestPath(space.tenantPath)}>Request service</Link></div> : null}
        <div className="mt-8 grid gap-4">
          {machines.isLoading ? (
            <div className="grid gap-4" aria-busy="true" aria-label="Loading machines">
              {[0, 1, 2].map((item) => <Skeleton key={item} className="h-40 w-full rounded-lg" />)}
            </div>
          ) : null}
          {machines.error ? <PublicLoadError error={machines.error} noun="machines" onRetry={() => machines.refetch()} /> : null}
          {machines.data && !groups.length ? (
            <EmptyState title="No machines listed" description="This makerspace has not published any machines yet." />
          ) : null}
          {groups.map((group) => (
            <CollapsibleSection
              key={group.id}
              title={group.name}
              icon={group.icon || null}
              count={group.machines.length}
              open={!collapsed.has(group.id)}
              onToggle={() => toggleGroup(group.id)}
            >
              {requestableIds.has(group.id) ? <div className="px-4 pt-4"><Link
                className={buttonClasses({ variant: "secondary", size: "sm" })}
                to={serviceRequestPath(space.tenantPath, group.id)}
                aria-label={`Request service for ${group.name}`}
              >Request service</Link></div> : null}
              <ul className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
                {/* The public projection carries no id; the API orders by (name, id), so name + position is stable. */}
                {group.machines.map((machine, index) => (
                  <li key={`${machine.name}-${index}`} className="overflow-hidden rounded-lg border border-line bg-canvas">
                    {/* Decorative: the machine name is rendered right below it. */}
                    {machine.image_url ? <img src={machine.image_url} alt="" loading="lazy" className="aspect-[16/9] w-full border-b border-line object-cover" /> : null}
                    <div className="grid gap-2 p-4">
                      <h3 className="truncate text-title text-ink">{machine.name}</h3>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={machine.status} />
                        <span className="text-caption text-ink-muted">{machine.usage_hours} h logged</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </CollapsibleSection>
          ))}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
