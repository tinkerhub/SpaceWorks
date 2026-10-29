import { Link } from "react-router-dom";
import { ChartColumn } from "lucide-react";

import { documentTitle, useDocumentTitle } from "../../lib/useDocumentTitle";
import { MakerspaceBrand } from "../MakerspaceBrand";
import { SpaceWorksLogo } from "../SpaceWorksLogo";
import { IconLink } from "../ui";
import { SiteHeader, type SiteNavLink } from "./SiteHeader";

const brandLinkClasses =
  "inline-flex min-w-0 max-w-full items-center rounded-md pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

type MakerspaceSiteHeaderProps = {
  /** The makerspace's public root: `/m/<slug>` centrally, `/` on its own domain. */
  homePath: string;
  name: string;
  logoUrl?: string | null;
  /** Off-module sections must not be linked: their pages are 404s. */
  moduleEnabled: (key: string) => boolean;
  statsEnabled?: boolean;
  /** This page's name, for the document title. */
  page: string;
};

/** Header for one makerspace's public pages: its brand, its enabled sections, sign-in links. */
export function MakerspaceSiteHeader({ homePath, name, logoUrl, moduleEnabled, statsEnabled, page }: MakerspaceSiteHeaderProps) {
  useDocumentTitle(documentTitle(page, name));
  const base = homePath.replace(/\/+$/, "");
  const at = (subpath: string) => `${base}/${subpath}`;
  const sections: (SiteNavLink & { module?: string })[] = [
    { to: base || "/", label: "Inventory", exact: true },
    { to: at("machines"), label: "Machines", module: "machines" },
    ...(moduleEnabled("machines") ? [{ to: at("machine-service"), label: "Service requests", module: "machine_service" }] : []),
    { to: at("events"), label: "Events", module: "events" },
    { to: at("bookings"), label: "Bookings", module: "bookings" },
  ];
  return (
    <SiteHeader
      brand={(
        <Link to={base || "/"} aria-label={`${name} home`} className={brandLinkClasses}>
          <MakerspaceBrand name={name} logoUrl={logoUrl} size="sm" />
        </Link>
      )}
      links={sections.filter((link) => !link.module || moduleEnabled(link.module))}
      extra={statsEnabled ? (
        <IconLink label="Stats" variant="quiet" to={at("stats")}>
          <ChartColumn />
        </IconLink>
      ) : null}
      actions={[
        // The member area is a 404 when member accounts are off, so it is not linked.
        ...(moduleEnabled("member_accounts") ? [{ to: at("member"), label: "Member area", variant: "quiet" as const }] : []),
        { to: "/admin", label: "Staff login", variant: "secondary" },
      ]}
    />
  );
}

/** Header for the platform's own pages (makerspace directory, about). */
export function PlatformSiteHeader({ page, homeLabel = "Makerspaces" }: { page: string; homeLabel?: string }) {
  useDocumentTitle(documentTitle(page));
  return (
    <SiteHeader
      brand={(
        <Link to="/" aria-label="Open makerspace listing" className={`${brandLinkClasses} text-ink`}>
          <SpaceWorksLogo size={26} withWordmark />
        </Link>
      )}
      links={[
        { to: "/", label: homeLabel, exact: true },
        { to: "/about", label: "About" },
      ]}
      actions={[{ to: "/admin", label: "Staff login", variant: "secondary" }]}
    />
  );
}
