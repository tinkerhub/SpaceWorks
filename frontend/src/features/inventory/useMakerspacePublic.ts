import { useParams } from "react-router-dom";

import { useTenant, useTenantPath } from "../../lib/tenant";
import { useTenantBootstrap } from "./usePublicInventory";

export function formatSlug(slug: string): string {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

/**
 * The makerspace a public page belongs to: the runtime tenant on a single-tenant
 * deployment, or the `/m/:slug` makerspace (and its bootstrap) on the central one.
 * `header` is what `MakerspaceSiteHeader` needs, minus the page-specific props.
 */
export function useMakerspacePublic() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const displayName =
    bootstrap?.branding?.display_name || bootstrap?.makerspace?.name || formatSlug(makerspaceSlug) || "Makerspace";
  return {
    tenant,
    makerspaceSlug,
    tenantPath,
    bootstrapQuery,
    bootstrap,
    displayName,
    header: {
      homePath: tenantPath(),
      name: displayName,
      logoUrl: bootstrap?.makerspace?.logo_url,
      statsEnabled: bootstrap?.makerspace?.public_stats_enabled,
    },
  };
}
