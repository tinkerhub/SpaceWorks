import { useEffect, useState } from "react";

import { Button, ErrorText, Input, Modal } from "../../../components/ui";
import type { HardwareRequest } from "./Queues";
import { ShelfLine } from "./QueuesModalShared";

type AcceptedQuantity = { item_id: number; quantity: number };

export function AcceptRequestModal({
  row,
  open,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  row: HardwareRequest | null;
  open: boolean;
  pending: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (acceptedQuantities: AcceptedQuantity[]) => void;
}) {
  const [quantities, setQuantities] = useState<Record<number, number>>({});

  useEffect(() => {
    if (!open || !row) return;
    // Default to full accept; the manager dials each line down as needed.
    setQuantities(Object.fromEntries(row.items.map((item) => [item.id, item.requested_quantity])));
  }, [open, row]);

  const total = Object.values(quantities).reduce((sum, value) => sum + (Number(value) || 0), 0);
  const canSubmit = total > 0 && !pending;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Accept request #${row.id}` : "Accept request"}
      description="Lower a line to approve part of it, or set 0 to decline that item."
      footer={
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={pending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="accept-request-form" disabled={total === 0} loading={pending}>
            Accept
          </Button>
        </div>
      }
    >
      <form
        id="accept-request-form"
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!row || !canSubmit) return;
          onSubmit(row.items.map((item) => ({ item_id: item.id, quantity: Number(quantities[item.id]) || 0 })));
        }}
      >
        <ul className="grid gap-2">
          {row?.items.map((item) => {
            const inputId = `accept-qty-${item.id}`;
            return (
              <li key={item.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-line px-4 py-3">
                <label htmlFor={inputId} className="min-w-0">
                  <span className="block text-label text-ink [overflow-wrap:anywhere]">{item.product_name}</span>
                  <span className="block text-caption text-ink-muted">Requested {item.requested_quantity}</span>
                  <ShelfLine location={item.storage_location} />
                </label>
                <Input
                  id={inputId}
                  className="w-24"
                  type="number"
                  min={0}
                  max={item.requested_quantity}
                  value={quantities[item.id] ?? item.requested_quantity}
                  disabled={pending}
                  onChange={(event) =>
                    setQuantities((current) => ({
                      ...current,
                      [item.id]: Math.max(0, Math.min(item.requested_quantity, Number(event.target.value) || 0)),
                    }))
                  }
                />
              </li>
            );
          })}
        </ul>
        {total === 0 ? <p className="text-caption text-warning-fg">Accept at least one unit, or reject the request instead.</p> : null}
        <ErrorText message={error} />
      </form>
    </Modal>
  );
}
