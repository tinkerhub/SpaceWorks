import type { FormEvent } from "react";

import { Button, Dropdown, ErrorText, Field, Input, SectionHeading } from "../../../components/ui";
import { StatusWord, type Makerspace, type Product } from "./shared";

export type ResolveTarget =
  | { type: "product"; id: number; name: string }
  | { type: "asset"; id: number; asset_tag: string; product: string; status: string }
  | { type: "box"; id: number; label: string; code: string };
export type ResolvedQr = { id: number; makerspace: number; makerspace_id?: number; payload: string; status: string };
export type Resolved = { qr: ResolvedQr; target: ResolveTarget; allowed_actions: string[] };
export type Rebound = { qr: ResolvedQr; target: ResolveTarget };
export type BoxContents = {
  products: { id: number; name: string; available_quantity: number }[];
  assets: { id: number; asset_tag: string; product: string; status: string }[];
};

const formClasses = "grid gap-4 rounded-lg border border-line bg-subtle p-4";

function submitWith(handler: () => void) {
  return (event: FormEvent) => {
    event.preventDefault();
    handler();
  };
}

export function targetTitle(target: ResolveTarget) {
  if (target.type === "box") return `Box: ${target.label}`;
  if (target.type === "product") return `Product: ${target.name}`;
  return `Asset: ${target.asset_tag} · ${target.product}`;
}

export function RebindForm({ makerspaceName, products, productsLoading, productId, onProductChange, newName, onNewNameChange, pending, errors, onSubmit, onCancel }: {
  makerspaceName: string;
  products: Product[];
  productsLoading: boolean;
  productId: string;
  onProductChange: (value: string) => void;
  newName: string;
  onNewNameChange: (value: string) => void;
  pending: boolean;
  errors: Array<string | undefined>;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <form className={formClasses} onSubmit={submitWith(() => { if (productId) onSubmit(); })}>
      <SectionHeading as="h3" title="Rename and rebind" description="Point this product QR at another product in its makerspace." />
      <Field label="QR makerspace"><Input value={makerspaceName} readOnly /></Field>
      <Field label="Target product">
        <Dropdown value={productId} disabled={productsLoading || !products.length} onChange={(event) => onProductChange(event.target.value)}>
          {products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
        </Dropdown>
      </Field>
      <Field label="New name" optional>
        <Input aria-label="Rename target" placeholder="Leave blank to keep the name" value={newName} onChange={(event) => onNewNameChange(event.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-2.5">
        <Button variant="primary" type="submit" disabled={!productId} loading={pending} loadingLabel="Saving…">Save</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
      {errors.map((message, index) => <ErrorText key={index} message={message} />)}
    </form>
  );
}

export function MoveAssetForm({ makerspaces, destMakerspaceId, onDestMakerspaceChange, products, productsLoading, destProductId, onDestProductChange, moveTag, onMoveTagChange, pending, errors, onSubmit, onCancel }: {
  makerspaces: Makerspace[];
  destMakerspaceId: string;
  onDestMakerspaceChange: (value: string) => void;
  products: Product[];
  productsLoading: boolean;
  destProductId: string;
  onDestProductChange: (value: string) => void;
  moveTag: string;
  onMoveTagChange: (value: string) => void;
  pending: boolean;
  errors: Array<string | undefined>;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <form className={formClasses} onSubmit={submitWith(() => { if (destMakerspaceId) onSubmit(); })}>
      <SectionHeading as="h3" title="Move to makerspace" description="Moves this unit and its QR to another makerspace." />
      <Field label="Destination makerspace">
        <Dropdown required value={destMakerspaceId} onChange={(event) => onDestMakerspaceChange(event.target.value)}>
          <option value="">Select makerspace</option>
          {makerspaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
        </Dropdown>
      </Field>
      <Field label="Destination product">
        <Dropdown value={destProductId} disabled={!destMakerspaceId || productsLoading} onChange={(event) => onDestProductChange(event.target.value)}>
          <option value="">Auto - match by name or create</option>
          {products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
        </Dropdown>
      </Field>
      <Field label="New asset tag" optional>
        <Input aria-label="New asset tag" placeholder="Leave blank to keep the tag" value={moveTag} onChange={(event) => onMoveTagChange(event.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-2.5">
        <Button variant="primary" type="submit" disabled={!destMakerspaceId} loading={pending} loadingLabel="Moving…">Move</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
      {errors.map((message, index) => <ErrorText key={index} message={message} />)}
    </form>
  );
}

export function BoxContentsList({ contents }: { contents: BoxContents }) {
  if (!contents.products.length && !contents.assets.length) {
    return <p className="rounded-lg border border-dashed border-line-strong px-4 py-3 text-body-ui text-ink-muted">This box is empty.</p>;
  }
  return (
    <section className="grid gap-2">
      <SectionHeading as="h3" title="Contents" />
      <ul className="grid divide-y divide-line rounded-lg border border-line">
        {contents.products.map((product) => (
          <li key={`p-${product.id}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-body-ui">
            <span className="text-ink">{product.name}</span>
            <span className="text-ink-muted">{product.available_quantity} available</span>
          </li>
        ))}
        {contents.assets.map((asset) => (
          <li key={`a-${asset.id}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-body-ui">
            <span className="font-mono text-ink">{asset.asset_tag}</span>
            <StatusWord status={asset.status} />
          </li>
        ))}
      </ul>
    </section>
  );
}
