import { Minus, Plus } from "lucide-react";

import { Button, Chip, IconButton } from "../../components/ui";
import { cn } from "../../lib/cn";
import { catalogPresentation } from "../../lib/catalogPresentation";
import type { Product } from "../../types/inventory";
import { AvailabilityBadge } from "./AvailabilityBadge";

type ProductCardProps = {
  product: Product;
  quantity: number;
  onDecrement: () => void;
  onIncrement: () => void;
  onOpenDetails: () => void;
};

/** The item code (TC-MCU-A), or the catalogue number for an item without a coded category. */
export function productCode(product: Pick<Product, "id" | "item_code">) {
  return product.item_code || `#${String(product.id).padStart(4, "0")}`;
}

/** Image placeholder: the item's first letters on a stable brand tint. Decorative. */
export function ProductInitials({ product, className }: { product: Product; className?: string }) {
  return (
    <div aria-hidden="true" className={cn("grid h-full w-full place-items-center", catalogPresentation(product.id).tint, className)}>
      <span className="font-display text-4xl font-extrabold opacity-60">{product.name.slice(0, 2)}</span>
    </div>
  );
}

/** Catalog card: image, name, code, short description, category, and the request stepper. */
export function ProductCard({ product, quantity, onDecrement, onIncrement, onOpenDetails }: ProductCardProps) {
  const unavailable = product.availability?.label === "Unavailable";

  return (
    <article className="group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-canvas transition-colors duration-180 ease-standard hover:border-line-strong">
      <button
        className="relative block aspect-[4/3] w-full overflow-hidden border-b border-line bg-subtle text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
        type="button"
        onClick={onOpenDetails}
        aria-label={`Open details for ${product.name}`}
      >
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-240 ease-standard group-hover:scale-[1.02] motion-reduce:group-hover:scale-100"
          />
        ) : (
          <ProductInitials product={product} />
        )}
        <AvailabilityBadge availability={product.availability} className="absolute left-3 top-3 max-w-[calc(100%-1.5rem)]" />
      </button>

      <div className="flex min-w-0 flex-1 flex-col gap-2 p-4">
        <div className="min-w-0">
          <h2 className="text-title text-ink">
            <button
              className="w-full min-w-0 max-w-full rounded-sm text-left pointer-coarse:-my-3 pointer-coarse:py-3 [overflow-wrap:anywhere] underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              type="button"
              onClick={onOpenDetails}
            >
              {product.name}
            </button>
          </h2>
          <p className="mt-0.5 font-mono text-caption text-ink-muted">{productCode(product)}</p>
        </div>
        <p className="line-clamp-2 text-body-ui text-ink-secondary">{product.description || "No description provided."}</p>
        {product.category_name ? (
          <div className="flex flex-wrap gap-2">
            <Chip size="sm">{product.category_name}</Chip>
          </div>
        ) : null}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
          <div className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-canvas p-0.5" role="group" aria-label={`Quantity of ${product.name}`}>
            <IconButton label={`Remove ${product.name}`} variant="quiet" size="sm" disabled={quantity === 0} onClick={onDecrement}>
              <Minus />
            </IconButton>
            <span className="min-w-7 text-center font-mono text-label tabular-nums text-ink" aria-live="polite">
              {quantity}
            </span>
            <IconButton label={`Add ${product.name}`} variant="quiet" size="sm" disabled={unavailable} onClick={onIncrement}>
              <Plus />
            </IconButton>
          </div>
          <Button variant="quiet" size="sm" onClick={onOpenDetails}>
            Details
          </Button>
        </div>
      </div>
    </article>
  );
}
