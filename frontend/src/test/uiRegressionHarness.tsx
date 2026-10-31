import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import type { TenantBootstrap } from "../lib/api";
import { queryClient } from "../lib/queryClient";
import { TenantProvider } from "../lib/tenant";
import type { CheckinMatch } from "../features/inventory/api";

export const rosterMatch: CheckinMatch = {
  mid: 443, name: "Ada Canonical", avatar: "", eligible: true, reason: "",
  purpose: "Working on a project", project_name: "Metrocard",
};

export function bootstrapFixture(slug: string): TenantBootstrap {
  return {
    makerspace: {
      id: slug === "a" ? 1 : 2, slug, name: `Lab ${slug}`, public_code: slug,
      location: "", geofence_enabled: false, membership_policy: "open",
      request_access: "checked_in", checkin: { provider: "Roster", purpose: "Working on a project" },
    },
    frontend: { type: "central", hostname: "", allowed_origins: [] },
    modules: ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"],
    features: ["inventory.self_checkout"], workflows: [], theme: {}, branding: {}, email_enabled: false,
    public_api: { base_url: "/api", publishable_key: "public-fixture", inventory_path: `/public/${slug}/inventory/` },
  };
}

export function regressionClient() {
  const defaults = queryClient.getDefaultOptions();
  const client = new QueryClient({ defaultOptions: {
    ...defaults, queries: { ...defaults.queries, retry: false }, mutations: { retry: false },
  } });
  for (const slug of ["a", "b"]) client.setQueryData(["tenant-bootstrap", slug], bootstrapFixture(slug));
  return client;
}

export function RegressionProviders({ client, children, path = "/m/a" }: {
  client: QueryClient; children: ReactNode; path?: string;
}) {
  return <QueryClientProvider client={client}>
    <TenantProvider><MemoryRouter initialEntries={[path]}>{children}</MemoryRouter></TenantProvider>
  </QueryClientProvider>;
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
