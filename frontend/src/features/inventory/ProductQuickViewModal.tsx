import { Button, Chip, Modal } from "../../components/ui";
import type { Product } from "../../types/inventory";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { ProductInitials, productCode } from "./ProductCard";

type ProductQuickViewModalProps = {
  product: Product | null;
  open: boolean;
  onClose: () => void;
};

function trackingLabel(product: Product): string {
  if (product.tracking_mode === "individual") return "Serialized";
  if (product.tracking_mode === "quantity") return "Quantity-tracked";
  return "Catalog item";
}

/** Item detail: large image beside the name, code, availability, chips and full description. */
export function ProductQuickViewModal({ product, open, onClose }: ProductQuickViewModalProps) {
  if (!product) return null;

  const description = product.description.trim() || "No description provided.";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={product.name}
      description={`Item ${productCode(product)}`}
      size="xl"
      footer={<Button onClick={onClose}>Close</Button>}
    >
      <div className="grid min-w-0 gap-6 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="relative aspect-[4/3] w-full min-w-0 self-start overflow-hidden rounded-lg border border-line bg-subtle md:aspect-square">
          {product.image_url ? (
            <img src={product.image_url} alt={product.name} className="h-full w-full object-cover" />
          ) : (
            <ProductInitials product={product} className="[&>span]:text-6xl" />
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <AvailabilityBadge availability={product.availability} size="md" />
            <Chip tone="info">{trackingLabel(product)}</Chip>
            {product.category_name ? <Chip>{product.category_name}</Chip> : null}
          </div>
          <section className="rounded-lg border border-line bg-subtle p-4">
            <h3 className="text-label text-ink">Description</h3>
            <p className="mt-2 whitespace-pre-wrap break-words text-body-ui text-ink-secondary">{description}</p>
          </section>
          <p className="text-caption text-ink-muted">
            Add this item from the catalog to include it in a borrow request.
          </p>
        </div>
      </div>
    </Modal>
  );
}
