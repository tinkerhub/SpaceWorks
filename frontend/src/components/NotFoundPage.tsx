import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { useTenantBootstrap } from "../features/inventory/usePublicInventory";
import { formatSlug } from "../features/inventory/useMakerspacePublic";
import { useTenant } from "../lib/tenant";
import { MakerspaceSiteHeader, PlatformSiteHeader } from "./chrome/PublicHeaders";
import { PublicShell } from "./chrome/PublicShell";
import { Button, buttonClasses } from "./ui";

/** `/m/<slug>/…` on the central deployment, read from the path when no route param exists. */
function centralSlug(pathname: string, param: string | undefined) {
  if (param) return param;
  return /^\/m\/([^/]+)/.exec(pathname)?.[1] ?? "";
}

/**
 * The page behind unknown paths and module-gated routes whose module is off. Inside a
 * makerspace it keeps that makerspace's header so the visitor is one click from its
 * inventory; elsewhere it uses the platform header.
 */
export function NotFoundPage() {
  const tenant = useTenant();
  const { pathname } = useLocation();
  const params = useParams();
  const navigate = useNavigate();
  const central = tenant.mode === "central";
  const slug = central ? centralSlug(pathname, params.slug) : tenant.slug;
  const bootstrapQuery = useTenantBootstrap(slug, central);
  const bootstrap = central ? bootstrapQuery.data : tenant.bootstrap;
  // A central path naming a makerspace that does not exist falls back to the platform header.
  const inMakerspace = central ? Boolean(slug) && !bootstrapQuery.isError : true;
  const homePath = central ? (inMakerspace ? `/m/${slug}` : "/") : "/";
  const name = bootstrap?.branding?.display_name || bootstrap?.makerspace?.name || formatSlug(slug) || "Makerspace";
  const modules = central ? bootstrap?.modules : [...tenant.modules];
  const moduleEnabled = (key: string) => Boolean(modules?.includes(key));

  const header = inMakerspace ? (
    <MakerspaceSiteHeader
      homePath={homePath}
      name={name}
      logoUrl={bootstrap?.makerspace?.logo_url}
      moduleEnabled={moduleEnabled}
      statsEnabled={bootstrap?.makerspace?.public_stats_enabled}
      page="Page not found"
    />
  ) : (
    <PlatformSiteHeader page="Page not found" />
  );

  return (
    <PublicShell header={header}>
      <div className="mx-auto flex w-full max-w-[560px] flex-1 flex-col items-center justify-center px-4 py-16 text-center sm:px-6">
        <p aria-hidden="true" className="font-display text-[72px] font-extrabold leading-none tracking-[-0.04em] text-accent-ink sm:text-[96px]">
          404
        </p>
        <h1 className="mt-4 text-h2 text-ink">Page not found</h1>
        <p className="mt-3 text-body-ui text-ink-secondary">
          {inMakerspace
            ? `This page doesn't exist, or ${name} hasn't turned this section on. The inventory is still open.`
            : "This page doesn't exist or has moved. Check the address, or start again from the home page."}
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
          <Link to={homePath} className={buttonClasses({ variant: "primary" })}>
            {inMakerspace ? "Back to the inventory" : "Go to the home page"}
          </Link>
          {inMakerspace && central ? (
            <Link to="/" className={buttonClasses({ variant: "secondary" })}>
              All makerspaces
            </Link>
          ) : null}
          <Button variant="quiet" startIcon={<ArrowLeft />} onClick={() => navigate(-1)}>
            Go back
          </Button>
        </div>
      </div>
    </PublicShell>
  );
}
