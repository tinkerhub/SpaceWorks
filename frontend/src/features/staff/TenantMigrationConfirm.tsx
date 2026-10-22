import { ConfirmDialog } from "../../components/ui";
import type { ReceiptEnvelope } from "./tenantMigrationApi";

/** Every one-way tenant-migration action, confirmed by naming the tenant. */
export type MigrationConfirm =
  | { kind: "quiesce"; jobId: string }
  | { kind: "archive"; pairingId: string }
  | { kind: "recover"; pairingId: string; receipt: ReceiptEnvelope }
  | { kind: "activate"; receipt: ReceiptEnvelope }
  | { kind: "abort" };

const copy: Record<MigrationConfirm["kind"], (name: string) => { title: string; message: string; label: string; typed: boolean }> = {
  quiesce: (name) => ({ title: `Quiesce ${name}?`, message: `This freezes source writes to ${name} before cutover.`, label: `Quiesce ${name}`, typed: false }),
  archive: (name) => ({ title: `Archive ${name}?`, message: `This source cutover of ${name} cannot be undone from this screen.`, label: `Archive ${name}`, typed: true }),
  recover: (name) => ({ title: `Recover archived source ${name}?`, message: `Use this only after the target of ${name} is aborted.`, label: `Recover ${name}`, typed: false }),
  activate: (name) => ({ title: `Activate ${name}?`, message: `This target cutover of ${name} cannot be undone from this screen.`, label: `Activate ${name}`, typed: true }),
  abort: (name) => ({ title: `Abort ${name}?`, message: `Imported target objects of ${name} will be rolled back.`, label: `Abort ${name}`, typed: false }),
};

export function TenantMigrationConfirm({ confirm, tenantName, pending, onConfirm, onCancel }: {
  confirm: MigrationConfirm | null;
  tenantName: string;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const text = confirm ? copy[confirm.kind](tenantName) : null;
  return (
    <ConfirmDialog
      open={confirm !== null}
      tone="danger"
      title={text?.title ?? ""}
      message={text?.message}
      confirmLabel={text?.label ?? "Confirm"}
      confirmText={text?.typed ? tenantName : undefined}
      pending={pending}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
