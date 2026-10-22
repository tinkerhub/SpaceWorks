import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { EmptyState, SectionHeading, Skeleton } from "../../../../components/ui";
import { MaintenanceDocuments } from "./MaintenanceDocuments";
import { MaintenanceLogForm } from "./MaintenanceLogForm";
import { MaintenanceSchedules } from "./MaintenanceSchedules";
import { useMaintenanceLogs, useMaintenanceSchedules, type MaintenanceSchedule } from "./maintenanceApi";
import { When } from "./machineUi";

type MaintenanceTabProps = {
  makerspaceId: number;
  machineId: number;
  canEdit: boolean;
  canOperate: boolean;
  enabled: boolean;
  retired: boolean;
};

export function MaintenanceTab({
  makerspaceId, machineId, canEdit, canOperate, enabled, retired,
}: MaintenanceTabProps) {
  const [completing, setCompleting] = useState<MaintenanceSchedule | null>(null);
  const schedules = useMaintenanceSchedules(makerspaceId, machineId, enabled);
  const logs = useMaintenanceLogs(makerspaceId, machineId, enabled);

  if (schedules.isLoading || logs.isLoading) {
    return (
      <div className="grid gap-3" role="status" aria-label="Loading maintenance details">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const queryError = schedules.error ?? logs.error;
  if (queryError instanceof Error) {
    return <EmptyState tone="error" title="Unable to load maintenance" description={queryError.message} />;
  }

  const scheduleRows = schedules.data?.results ?? [];
  const logRows = logs.data?.results ?? [];

  return (
    <div className="grid gap-8">
      <MaintenanceSchedules
        makerspaceId={makerspaceId}
        machineId={machineId}
        schedules={scheduleRows}
        canEdit={canEdit}
        retired={retired}
        onComplete={setCompleting}
      />
      {completing ? (
        <MaintenanceLogForm
          key={completing.id}
          makerspaceId={makerspaceId}
          machineId={machineId}
          schedule={completing}
          onCancel={() => setCompleting(null)}
          onLogged={() => setCompleting(null)}
        />
      ) : null}
      {canOperate && !retired && !completing ? (
        <MaintenanceLogForm makerspaceId={makerspaceId} machineId={machineId} />
      ) : null}
      <section className="grid gap-3" aria-labelledby="maintenance-history-title">
        <SectionHeading as="h3" title={<span id="maintenance-history-title">Maintenance history</span>} description="Open a record for its parts notes and attachments." />
        {!logRows.length ? (
          <EmptyState
            title="No maintenance logged"
            description="Completed maintenance records will appear here."
          />
        ) : null}
        {logRows.length ? (
          <ul className="grid gap-2">
            {logRows.map((log) => (
              <li key={log.id}>
                <details className="group rounded-lg border border-line bg-canvas">
                  <summary className="flex min-h-11 cursor-pointer list-none items-start gap-3 rounded-lg p-4 hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
                    <ChevronRight aria-hidden="true" className="mt-0.5 size-[18px] shrink-0 text-ink-muted transition-transform duration-180 ease-standard group-open:rotate-90" />
                    <span className="grid min-w-0 flex-1 gap-0.5">
                      <strong className="text-body-ui font-semibold text-ink">{log.summary}</strong>
                      <span className="text-caption text-ink-muted">
                        <When value={log.performed_at} />
                        {log.cost ? ` · Cost ${log.cost}` : ""}
                        {log.documents.length ? ` · ${log.documents.length} ${log.documents.length === 1 ? "attachment" : "attachments"}` : ""}
                      </span>
                    </span>
                  </summary>
                  <div className="grid gap-3 border-t border-line p-4 text-body-ui text-ink-secondary">
                    {log.parts_note ? (
                      <p className="whitespace-pre-wrap break-words">{log.parts_note}</p>
                    ) : <p className="text-ink-muted">No parts notes.</p>}
                    <MaintenanceDocuments
                      machineId={machineId}
                      logId={log.id}
                      documents={log.documents}
                      canDelete={canEdit}
                      retired={retired}
                    />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
