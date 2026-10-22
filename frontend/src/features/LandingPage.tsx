import { useDeferredValue, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { MakerspaceBrand } from "../components/MakerspaceBrand";
import { MakerspaceMapLink } from "../components/MakerspaceMapLink";
import { PlatformSiteHeader } from "../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../components/chrome/PublicShell";
import { Chip, EmptyState, Field, PageHeader, SearchInput, Skeleton, StatusChip } from "../components/ui";
import { catalogPresentation } from "../lib/catalogPresentation";
import type { Makerspace } from "../types/inventory";
import { usePublicMakerspaces } from "./inventory/usePublicInventory";

function normalizeSearch(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function makerspaceSearchText(makerspace: Makerspace) {
  return normalizeSearch([
    makerspace.name,
    makerspace.public_code,
    makerspace.slug,
    makerspace.location,
  ].filter(Boolean).join(" "));
}

export function LandingPage() {
  const makerspacesQuery = usePublicMakerspaces();
  const [searchInput, setSearchInput] = useState("");
  const searchQuery = normalizeSearch(useDeferredValue(searchInput));
  const searchTokens = useMemo(
    () => searchQuery.split(" ").filter(Boolean),
    [searchQuery],
  );
  const indexedMakerspaces = useMemo(
    () => (makerspacesQuery.data ?? []).map((makerspace) => ({
      makerspace,
      searchText: makerspaceSearchText(makerspace),
    })),
    [makerspacesQuery.data],
  );
  const filteredMakerspaces = useMemo(() => {
    if (!searchTokens.length) return indexedMakerspaces.map(({ makerspace }) => makerspace);
    return indexedMakerspaces
      .filter(({ searchText }) => searchTokens.every((token) => searchText.includes(token)))
      .map(({ makerspace }) => makerspace);
  }, [indexedMakerspaces, searchTokens]);
  const totalMakerspaces = makerspacesQuery.data?.length ?? 0;
  const onlyMakerspace = totalMakerspaces === 1 ? makerspacesQuery.data?.[0] : null;

  if (onlyMakerspace) return <Navigate replace to={`/m/${onlyMakerspace.slug}`} />;

  return (
    <PublicShell header={<PlatformSiteHeader page="Makerspaces" />}>
      <PublicContainer>
        <PageHeader
          kicker="Inventory directory"
          title="Makerspaces"
          description="Browse public catalogs across connected workshops, labs and community spaces."
          actions={<Chip tone="secondary">{makerspacesQuery.isLoading ? "–" : totalMakerspaces} public spaces</Chip>}
        />

        <form className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center" role="search" onSubmit={(event) => event.preventDefault()}>
          <Field className="min-w-0 flex-1 sm:max-w-[520px]" label="Search makerspaces" hideLabel id="makerspace-search">
            <SearchInput
              placeholder="Search by name, code, slug or location"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onClear={() => setSearchInput("")}
            />
          </Field>
          <p className="shrink-0 text-body-ui text-ink-muted" aria-live="polite">
            {searchQuery ? `${filteredMakerspaces.length} of ${totalMakerspaces}` : totalMakerspaces} shown
          </p>
        </form>

        <div className="mt-6">
          {makerspacesQuery.isLoading ? (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading makerspaces">
              {[0, 1, 2].map((item) => (
                <div key={item} className="overflow-hidden rounded-lg border border-line bg-canvas">
                  <Skeleton className="aspect-[16/9] w-full rounded-none" />
                  <div className="space-y-2 p-5"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>
                </div>
              ))}
            </div>
          ) : null}
          {makerspacesQuery.isError ? (
            <EmptyState tone="error" title="Makerspaces are unavailable" description="The public makerspace directory could not be loaded." />
          ) : null}
          {makerspacesQuery.data && !makerspacesQuery.data.length ? (
            <EmptyState title="No public makerspaces yet" description="Public inventory appears here after a makerspace is enabled." />
          ) : null}
          {makerspacesQuery.data && makerspacesQuery.data.length > 0 && !filteredMakerspaces.length ? (
            <EmptyState title="No matching makerspaces" description="Try another name, makerspace code, URL slug or location." />
          ) : null}

          {filteredMakerspaces.length ? (
            <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {filteredMakerspaces.map((makerspace) => (
                <li key={makerspace.slug} className="min-w-0">
                  <article className="group relative flex h-full flex-col overflow-hidden rounded-lg border border-line bg-canvas transition-colors duration-180 ease-standard hover:bg-subtle focus-within:border-line-strong">
                    <div className={`relative aspect-[16/9] overflow-hidden border-b border-line ${catalogPresentation(makerspace.slug).tint}`}>
                      {makerspace.cover_image_url ? (
                        <img src={makerspace.cover_image_url} alt={`${makerspace.name} cover`} loading="lazy" className="h-full w-full object-cover transition-transform duration-240 ease-standard group-hover:scale-[1.02] motion-reduce:group-hover:scale-100" />
                      ) : null}
                      <StatusChip tone="success" size="sm" className="absolute left-3 top-3">Public</StatusChip>
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col p-5">
                      <MakerspaceBrand name={makerspace.name} logoUrl={makerspace.logo_url} size="md" />
                      <MakerspaceMapLink makerspace={makerspace} className="relative z-10 mt-2" />
                      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-5">
                        <Chip size="sm" className="min-w-0 font-mono">{makerspace.public_code}</Chip>
                        <Link
                          className="inline-flex min-h-11 items-center gap-1.5 rounded-sm text-label text-accent-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus after:absolute after:inset-0 after:content-['']"
                          to={`/m/${makerspace.slug}`}
                          aria-label={`Open ${makerspace.name} catalog`}
                        >
                          Open catalog
                          <ArrowRight aria-hidden="true" className="size-4" />
                        </Link>
                      </div>
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
