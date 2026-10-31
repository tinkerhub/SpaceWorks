import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight } from "lucide-react";

import { PlatformSiteHeader } from "../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../components/chrome/PublicShell";
import { PageHeader } from "../components/ui";
import { useTenant } from "../lib/tenant";

const cardClasses =
  "group flex items-start justify-between gap-4 rounded-xl p-6 transition-colors duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function AboutPage() {
  const tenant = useTenant();
  return (
    <PublicShell header={<PlatformSiteHeader page="About" homeLabel={tenant.mode === "single" ? "Inventory" : "Makerspaces"} />}>
      <PublicContainer width="md">
        <PageHeader kicker="About" title="Open source makerspace manager" />
        <div className="mt-6 max-w-[640px] space-y-4 text-body-l text-ink-secondary">
          <p>
            Space Works is a platform for running community makerspaces: public equipment catalogs,
            hardware lending with traceable handovers, 3D-print request queues, and multi-makerspace
            operations in one place.
          </p>
          <p>
            Each makerspace controls its own inventory, branding, staff and notifications. Visitors
            browse catalogs and request equipment; staff handle approvals, issue and return with
            evidence, and reporting.
          </p>
          <p className="text-body-ui text-ink-muted">
            Space Works is free and open source software, licensed under the{" "}
            <a
              className="font-semibold text-ink underline underline-offset-4 hover:text-accent-ink"
              href="https://github.com/SpaceWorks-Labs/SpaceWorks/blob/main/LICENSE"
              target="_blank"
              rel="noopener noreferrer"
            >
              GNU Affero General Public License v3
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            . Free to use, study, share and modify under the terms of the AGPL.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          <a
            className={`${cardClasses} border border-line bg-secondary/25 hover:bg-secondary/35`}
            href="https://github.com/SpaceWorks-Labs/SpaceWorks"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>
              <span className="block text-h4 text-ink">Use SpaceWorks for your space</span>
              <span className="mt-1 block text-body-ui text-ink-secondary">Get the official project and installation guide for your makerspace.</span>
              <span className="sr-only"> (opens in a new tab)</span>
            </span>
            <ArrowUpRight aria-hidden="true" className="mt-1 size-5 shrink-0 text-ink" />
          </a>
          <a
            className={`${cardClasses} border border-line bg-accent/20 hover:bg-accent/30`}
            href="https://github.com/tinkerhub/SpaceWorks"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>
              <span className="block text-h4 text-ink">Contribute to TinkerSpace's SpaceWorks</span>
              <span className="mt-1 block text-body-ui text-ink-secondary">Help improve this community's setup with ideas, bug reports, code or documentation.</span>
              <span className="sr-only"> (opens in a new tab)</span>
            </span>
            <ArrowUpRight aria-hidden="true" className="mt-1 size-5 shrink-0 text-ink" />
          </a>
          <Link className={`${cardClasses} bg-accent/20 hover:bg-accent/30`} to="/">
            <span>
              <span className="block text-h4 text-ink">Browse makerspaces</span>
              <span className="mt-1 block text-body-ui text-ink-secondary">View public equipment catalogs.</span>
            </span>
            <ArrowRight aria-hidden="true" className="mt-1 size-5 shrink-0 text-ink transition-transform duration-180 group-hover:translate-x-0.5" />
          </Link>
          <Link className={`${cardClasses} bg-secondary/25 hover:bg-secondary/35`} to="/admin">
            <span>
              <span className="block text-h4 text-ink">Staff login</span>
              <span className="mt-1 block text-body-ui text-ink-secondary">Manage your makerspace.</span>
            </span>
            <ArrowRight aria-hidden="true" className="mt-1 size-5 shrink-0 text-ink transition-transform duration-180 group-hover:translate-x-0.5" />
          </Link>
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
