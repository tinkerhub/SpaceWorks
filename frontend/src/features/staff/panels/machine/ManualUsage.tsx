import { Button, Dropdown, Field, Input, StatusChip, Table, TBody, TD, TH, THead, TR } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import type { Machine } from "../../machinesApi";
import type { ServiceDraft } from "./serviceDrafts";
import { poolLabel } from "./servicePools";

export type ManualUsageRow = { id: number; outcome: string; used: string; minutes: number; percent?: number | null };

type Props = {
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
  machines: Machine[];
  pools: PrinterPool[];
  /** "Machine" or "Printer". */
  machineNoun: string;
  unitLabel: string;
  hasPool: boolean;
  pending: boolean;
  onSubmit: () => void;
  rows: ManualUsageRow[];
};

export const blankManualUsage: ServiceDraft["manual"] = {
  machine_id: "", consumable_pool_id: "", duration_minutes: "", quantity: "",
  outcome: "success", percent_complete: "100", reason: "", note: "",
};

/** Log a run that happened outside the queue, and list the ones already logged. */
export function ManualUsage({ draft, setDraft, machines, pools, machineNoun, unitLabel, hasPool, pending, onSubmit, rows }: Props) {
  const manual = draft.manual;
  const noun = machineNoun.toLowerCase();
  const update = (patch: Partial<typeof manual>) => setDraft((current) => ({ ...current, manual: { ...current.manual, ...patch } }));
  return (
    <div className="grid gap-4">
      <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-2 md:grid-cols-4 md:items-end" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <Field label={machineNoun}>
          <Dropdown aria-label={`Manual usage ${noun}`} value={manual.machine_id} onChange={(event) => update({ machine_id: event.target.value, consumable_pool_id: "" })}>
            <option value="" disabled>Choose a {noun}</option>
            {machines.map((machine) => <option key={machine.id} value={String(machine.id)}>{machine.name}</option>)}
          </Dropdown>
        </Field>
        {hasPool ? (
          <Field label="Pool">
            <Dropdown aria-label="Manual usage pool" value={manual.consumable_pool_id} onChange={(event) => update({ consumable_pool_id: event.target.value })}>
              <option value="">No pool</option>
              {pools.map((pool) => <option key={pool.id} value={String(pool.id)}>{poolLabel(pool)}</option>)}
            </Dropdown>
          </Field>
        ) : null}
        <Field label="Minutes">
          <Input aria-label="Manual usage minutes" type="number" min="0" value={manual.duration_minutes} onChange={(event) => update({ duration_minutes: event.target.value })} />
        </Field>
        {hasPool ? (
          <Field label={unitLabel.charAt(0).toUpperCase() + unitLabel.slice(1)}>
            <Input aria-label={`Manual usage ${unitLabel}`} type="number" min="0" value={manual.quantity} onChange={(event) => update({ quantity: event.target.value })} />
          </Field>
        ) : null}
        <Field label="Outcome">
          <Dropdown aria-label="Manual usage outcome" value={manual.outcome} onChange={(event) => update({ outcome: event.target.value, percent_complete: event.target.value === "failed" ? manual.percent_complete : "100" })}>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </Dropdown>
        </Field>
        {/* A failed run credits only the share that ran. The generic form used to send the
            default 100 here with no field to change it, logging every failure as a full run;
            switching back to Success resets it to 100 so a success is never part-credited. */}
        {manual.outcome === "failed" ? (
          <>
            <Field label="Percent complete">
              <Input aria-label="Percent complete" type="number" min="0" max="100" value={manual.percent_complete} onChange={(event) => update({ percent_complete: event.target.value })} />
            </Field>
            <Field label="Failure reason">
              <Input aria-label="Failure reason" value={manual.reason} onChange={(event) => update({ reason: event.target.value })} />
            </Field>
          </>
        ) : null}
        <Field label="Note" className="sm:col-span-2">
          <Input aria-label="Manual usage note" value={manual.note} onChange={(event) => update({ note: event.target.value })} />
        </Field>
        <Button type="submit" loading={pending} loadingLabel="Logging…" disabled={!manual.machine_id || !manual.duration_minutes}>Log usage</Button>
      </form>
      {rows.length ? (
        <Table label="Manual usage log">
          <THead><tr><TH>Outcome</TH><TH>Used</TH><TH>Duration</TH></tr></THead>
          <TBody>
            {rows.map((row) => (
              <TR key={row.id}>
                <TD>
                  <StatusChip size="sm" tone={row.outcome === "failed" ? "danger" : "success"}>
                    {row.outcome === "failed" ? `Failed${row.percent !== null && row.percent !== undefined ? ` at ${row.percent}%` : ""}` : "Success"}
                  </StatusChip>
                </TD>
                <TD className="tabular-nums">{row.used}</TD>
                <TD className="tabular-nums">{row.minutes} min</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      ) : null}
    </div>
  );
}
