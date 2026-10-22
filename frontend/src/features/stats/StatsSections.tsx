import { Chip, StatTile, TBody, TD, TH, THead, TR, Table } from "../../components/ui";
import { ImageThumbnail } from "../../components/ui/ImageThumbnail";
import type { PublicStatsCurrentLoan, PublicStatsHardware, PublicStatsPrinting } from "./api";
import { BarChart, CompactList, Panel, Section, formatDate, formatNumber } from "./StatsParts";

export function PrintingSection({ printing }: { printing: PublicStatsPrinting }) {
  const queue = printing.jobs.queue;
  const queueTotal = queue.pending + queue.accepted + queue.printing;

  return (
    <Section title="Printing" description="3D printing activity across this makerspace's printers.">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Print hours all time" value={formatNumber(printing.hours_all_time)} />
        <StatTile label="Print hours this month" value={formatNumber(printing.hours_this_month)} />
        <StatTile label="Filament used" value={`${formatNumber(printing.grams_all_time)} g`} />
        <StatTile label="Completed jobs" value={printing.jobs.completed} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Busiest printer">
          {printing.busiest_printer ? (
            <div className="mt-3 flex items-center gap-3">
              <ImageThumbnail src={printing.busiest_printer.image_url} alt={printing.busiest_printer.name} className="h-16 w-16" />
              <div className="min-w-0">
                <p className="break-words text-h4 text-ink">{printing.busiest_printer.name}</p>
                {printing.busiest_printer.model ? (
                  <p className="break-words text-caption text-ink-muted">{printing.busiest_printer.model}</p>
                ) : null}
                <p className="text-caption tabular-nums text-ink-secondary">
                  {formatNumber(printing.busiest_printer.hours)} hours · {printing.busiest_printer.completed} completed
                </p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-body-ui text-ink-muted">No printer activity yet.</p>
          )}
        </Panel>

        <Panel title="Queue">
          <div className="mt-3 flex flex-wrap gap-2">
            <Chip tone="info">{queue.pending} pending</Chip>
            <Chip>{queue.accepted} accepted</Chip>
            <Chip>{queue.printing} printing</Chip>
            <Chip tone="outline">{queueTotal} active</Chip>
          </div>
        </Panel>

        <Panel title="By brand">
          <CompactList
            empty="No filament records."
            rows={printing.by_brand.map((row) => ({ label: row.brand, value: `${formatNumber(row.grams)} g` }))}
          />
        </Panel>
      </div>

      <Panel title="Filament trend">
        <div className="mt-4">
          <BarChart rows={printing.filament_trend.map((row) => ({ label: row.period, value: row.grams }))} valueLabel="g" />
        </div>
      </Panel>

      <div className="space-y-3">
        <h3 className="text-title text-ink">Per printer</h3>
        {printing.per_printer.length ? (
          <Table label="Per printer">
            <THead>
              <tr>
                <TH>Printer</TH>
                <TH className="text-right">Completed jobs</TH>
                <TH className="text-right">Hours</TH>
                <TH className="text-right">Filament (g)</TH>
              </tr>
            </THead>
            <TBody>
              {printing.per_printer.map((row, index) => (
                <TR key={`${row.name}-${index}`}>
                  <TD>
                    <div className="flex items-center gap-3">
                      <ImageThumbnail src={row.image_url} alt={row.name} />
                      <span className="min-w-0 break-words">
                        {row.name}
                        {row.model ? <span className="block text-caption text-ink-muted">{row.model}</span> : null}
                      </span>
                    </div>
                  </TD>
                  <TD className="text-right tabular-nums">{row.jobs}</TD>
                  <TD className="text-right tabular-nums">{formatNumber(row.hours)}</TD>
                  <TD className="text-right tabular-nums">{formatNumber(row.grams)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="rounded-lg border-[1.5px] border-dashed border-line-strong px-4 py-6 text-center text-body-ui text-ink-muted">No printer activity yet.</p>
        )}
      </div>
    </Section>
  );
}

export function HardwareSection({ hardware }: { hardware: PublicStatsHardware }) {
  return (
    <Section title="Hardware" description="The public tool library and how it's being used.">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Public library" value={hardware.library.library_size} />
        <StatTile label="Available now" value={hardware.library.available_count} />
        <StatTile label="Currently out" value={hardware.library.currently_out_count} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Most popular">
          <CompactList
            empty="No lending history yet."
            rows={hardware.most_popular.map((row) => ({
              label: row.name,
              value: `${row.times_lent} loans · ${row.total_quantity_lent} total`,
            }))}
          />
        </Panel>
        <Panel title="Tools out">
          <CompactList
            empty="No tools are out."
            rows={hardware.tools_out.map((row) => ({ label: row.name, value: `${row.quantity_out} out` }))}
          />
        </Panel>
        <Panel title="Recently added">
          <CompactList
            empty="No new public gear this month."
            rows={hardware.recently_added.map((row) => ({ label: row.name, value: formatDate(row.created_at) }))}
          />
        </Panel>
      </div>
    </Section>
  );
}

export function CurrentLoansSection({ loans }: { loans: PublicStatsCurrentLoan[] }) {
  return (
    <Section title="Currently out">
      {loans.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {loans.map((loan, index) => (
            <article className="min-w-0 rounded-lg border border-line bg-canvas p-4" key={`${loan.item_name}-${loan.holder_name}-${index}`}>
              <h3 className="truncate text-title text-ink">{loan.item_name}</h3>
              <p className="mt-1 text-body-ui text-ink-muted [overflow-wrap:anywhere]">
                With <span className="font-semibold text-ink">{loan.holder_name}</span>
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Chip size="sm" tone={loan.due ? "warning" : "neutral"}>Due {loan.due ? formatDate(loan.due) : "not set"}</Chip>
                {loan.since ? <Chip size="sm">Since {formatDate(loan.since)}</Chip> : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="rounded-lg border-[1.5px] border-dashed border-line-strong px-4 py-6 text-center text-body-ui text-ink-muted">
          No public tools are currently out.
        </p>
      )}
    </Section>
  );
}
