import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { NotFoundPage } from "../components/NotFoundPage";
import { Spinner } from "../components/ui/Spinner";
import { bootstrapTenant } from "./api";
import { useTenant } from "./tenant";

// The single place the frontend asks "is this module on?". Every gate fails CLOSED: a module
// list that is still loading, failed to load or is absent enables nothing, because showing a
// surface for a module the operator switched off is the bug these gates exist to prevent, and
// a loading flash is cheaper than a page that renders and then 400s on every request.
//
// Staff surfaces pass `activeMakerspace.enabled_modules`; public surfaces use `useModules()`,
// which reads the tenant bootstrap -- the runtime tenant on a single-tenant deployment, or the
// `/m/:slug` makerspace's own bootstrap on the central one.

type ModuleList = readonly string[] | ReadonlySet<string> | null | undefined;

export function moduleEnabled(modules: ModuleList, key: string): boolean {
  if (!modules) return false;
  return modules instanceof Set ? modules.has(key) : (modules as readonly string[]).includes(key);
}

export type ModulesState = {
  loading: boolean;
  modules: ReadonlySet<string> | null;
  moduleEnabled: (key: string) => boolean;
};

export function useModules(): ModulesState {
  const tenant = useTenant();
  const { slug = "" } = useParams();
  const central = tenant.mode === "central";
  // Same key and request as `useTenantBootstrap`, so the page underneath reuses this cache
  // entry instead of fetching the bootstrap a second time.
  const bootstrap = useQuery({
    queryKey: ["tenant-bootstrap", slug],
    queryFn: () => bootstrapTenant({ slug }),
    enabled: central && Boolean(slug),
  });
  let modules: ReadonlySet<string> | null;
  let loading: boolean;
  if (central) {
    modules = bootstrap.data ? new Set(bootstrap.data.modules) : null;
    loading = Boolean(slug) && bootstrap.isLoading;
  } else {
    modules = tenant.bootstrap ? tenant.modules : null;
    loading = tenant.loading;
  }
  return { loading, modules, moduleEnabled: (key) => moduleEnabled(modules, key) };
}

/** Renders `children` only when `module` is on; the not-found page otherwise. */
export function RequireModule({ module, children }: { module: string; children: ReactNode }) {
  const modules = useModules();
  if (modules.loading) {
    return (
      <main className="grid min-h-screen place-items-center bg-bg px-6" aria-busy="true">
        <div className="flex flex-col items-center gap-3 text-sm text-muted">
          <Spinner decorative />
          Loading…
        </div>
      </main>
    );
  }
  if (!modules.moduleEnabled(module)) return <NotFoundPage />;
  return <>{children}</>;
}
