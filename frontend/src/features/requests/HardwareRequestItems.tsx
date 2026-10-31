import type { PublicRequestStatus } from "../../types/inventory";

export function HardwareRequestItems({ items }: { items: PublicRequestStatus["items"] }) {
  return <ul className="divide-y divide-line">
    {items.map((item, index) => <li key={`${item.product_name}-${index}`} className="space-y-2 py-3 text-body-ui">
      <p className="break-words font-semibold text-ink">{item.product_name}</p>
      <dl className="flex flex-wrap gap-x-5 gap-y-2 text-caption text-ink-secondary">
        <div><dt>Requested</dt><dd className="font-semibold text-ink">{item.requested_quantity}</dd></div>
        {item.accepted_quantity !== undefined ? <div><dt>Approved</dt><dd className="font-semibold text-ink">{item.accepted_quantity}</dd></div> : null}
        {item.issued_quantity !== undefined ? <div><dt>Handed out</dt><dd className="font-semibold text-ink">{item.issued_quantity}</dd></div> : null}
        {item.returned_quantity !== undefined ? <div><dt>Returned</dt><dd className="font-semibold text-ink">{item.returned_quantity}</dd></div> : null}
      </dl>
    </li>)}
  </ul>;
}
