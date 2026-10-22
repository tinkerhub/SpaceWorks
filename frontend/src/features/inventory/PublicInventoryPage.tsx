import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { MakerspaceMapLink } from "../../components/MakerspaceMapLink";
import { Button, Chip, Field, PageHeader, Pagination, SearchInput } from "../../components/ui";
import { featureEnabled } from "../../lib/features";
import { useModules } from "../../lib/modules";
import type { Product, RequestCartItem } from "../../types/inventory";
import { ProductCard } from "./ProductCard";
import { ProductQuickViewModal } from "./ProductQuickViewModal";
import { CatalogFilters, EmptyState, ErrorState, LoadingState, type View } from "./PublicInventoryParts";
import { PublicRequestPanel } from "./PublicRequestPanel";
import { RequestCartBar } from "./RequestCartBar";
import { useMakerspacePublic } from "./useMakerspacePublic";
import { usePublicCategories, usePublicInventory } from "./usePublicInventory";

const PAGE_SIZE = 24;

function maxQuantity(product: Product): number {
  if (product.availability?.mode === "exact_count" && typeof product.availability.count === "number") {
    return product.availability.count;
  }
  return 99;
}

export function PublicInventoryPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug, bootstrap, displayName } = space;
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ kind: "all" });
  const [cart, setCart] = useState<Record<number, RequestCartItem>>({});
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const categoryParam = view.kind === "category" ? view.slug : "";
  const sortParam = view.kind === "sort" ? view.sort : "name";
  const categoriesQuery = usePublicCategories(makerspaceSlug);
  const inventoryQuery = usePublicInventory(makerspaceSlug, page, query, categoryParam, sortParam);
  const { moduleEnabled } = useModules();
  const categories = categoriesQuery.data ?? [];
  const products = inventoryQuery.data?.results ?? [];
  const count = inventoryQuery.data?.count;
  const pageCount = Math.max(1, Math.ceil((count ?? 0) / PAGE_SIZE));
  const selectedItems = useMemo(() => Object.values(cart), [cart]);
  const selectedCount = selectedItems.reduce((total, item) => total + item.quantity, 0);

  function incrementItem(product: Product) {
    if (product.availability?.label === "Unavailable") return;
    setCart((current) => {
      const existing = current[product.id];
      const quantity = Math.min((existing?.quantity ?? 0) + 1, maxQuantity(product));
      return { ...current, [product.id]: { productId: product.id, name: product.name, quantity } };
    });
  }

  function decrementItem(product: Product) {
    setCart((current) => {
      const existing = current[product.id];
      if (!existing || existing.quantity <= 1) {
        const next = { ...current };
        delete next[product.id];
        return next;
      }
      return { ...current, [product.id]: { ...existing, quantity: existing.quantity - 1 } };
    });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(searchInput.trim());
    setPage(1);
  }

  function clearSearch() {
    setSearchInput("");
    setQuery("");
    setPage(1);
  }

  function selectView(next: View) {
    setView(next);
    setPage(1);
  }

  return (
    <PublicShell width="xl" header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Inventory" />}>
      <PublicContainer width="xl" className={selectedCount > 0 ? "pb-24 md:pb-10" : undefined}>
        <PageHeader
          kicker="Public inventory"
          title={<MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace?.logo_url} size="xl" />}
          description="Shared tools and equipment published by this makerspace."
          actions={<Chip tone="secondary">{count ?? "–"} listed items</Chip>}
        />
        <MakerspaceMapLink makerspace={bootstrap?.makerspace} className="mt-2" />

        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-5">
            <div className="space-y-4">
              <form className="flex flex-col gap-2.5 sm:flex-row" role="search" onSubmit={submitSearch}>
                <Field className="min-w-0 flex-1" label="Search inventory" hideLabel>
                  <SearchInput
                    placeholder="Search tools, machines, kits or materials"
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                    onClear={searchInput || query ? clearSearch : undefined}
                  />
                </Field>
                <Button type="submit" className="shrink-0">Search</Button>
              </form>
              <CatalogFilters categories={categories} view={view} onSelect={selectView} />
            </div>

            {inventoryQuery.isLoading ? <LoadingState /> : null}
            {inventoryQuery.isError ? <ErrorState error={inventoryQuery.error} /> : null}
            {inventoryQuery.data && products.length === 0 ? <EmptyState query={query} onClear={clearSearch} /> : null}

            {products.length > 0 ? (
              <>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy={inventoryQuery.isFetching || undefined}>
                  {products.map((product) => (
                    <ProductCard
                      key={product.id}
                      product={product}
                      quantity={cart[product.id]?.quantity ?? 0}
                      onDecrement={() => decrementItem(product)}
                      onIncrement={() => incrementItem(product)}
                      onOpenDetails={() => setSelectedProduct(product)}
                    />
                  ))}
                </div>
                <Pagination page={page} totalPages={pageCount} onChange={setPage} count={count} pageSize={PAGE_SIZE} />
              </>
            ) : null}
          </div>

          <div id="request-desk" tabIndex={-1} className="min-w-0 scroll-mt-20 outline-none">
            <PublicRequestPanel
              items={selectedItems}
              makerspaceSlug={makerspaceSlug}
              onClear={() => setCart({})}
              disabled={!moduleEnabled("request_workflow")}
              requestAccess={bootstrap?.makerspace?.request_access}
              membershipOn={moduleEnabled("membership")}
              selfCheckout={featureEnabled(bootstrap?.features ?? [], "inventory.self_checkout")}
              memberAccountsOn={moduleEnabled("member_accounts")}
              memberAreaHref={`${space.header.homePath.replace(/\/+$/, "")}/member`}
            />
          </div>
        </div>
      </PublicContainer>

      {moduleEnabled("request_workflow") ? <RequestCartBar count={selectedCount} targetId="request-desk" /> : null}
      <ProductQuickViewModal product={selectedProduct} open={Boolean(selectedProduct)} onClose={() => setSelectedProduct(null)} />
    </PublicShell>
  );
}
