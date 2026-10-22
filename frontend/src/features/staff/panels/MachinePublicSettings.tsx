import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Card, SectionHeading, Skeleton, SwitchRow } from '../../../components/ui';
import {
  getMachinePublicPreview,
  machineKeys,
  machinePublicPreviewKey,
  setMachinePublicity,
  type Machine,
  type MachinePublicPreview,
} from '../machinesApi';
import { humanize, useNotify } from './machine/machineUi';

function PreviewValue({ value }: { value: unknown }) {
  if (value === null) return <span className="text-ink-muted">Not set</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  return (
    <dl className="grid gap-2">
      {Object.entries(value).map(([key, child]) => (
        <div key={key} className="grid gap-0.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
          <dt className="text-caption font-semibold text-ink-muted">{humanize(key)}</dt>
          <dd className="min-w-0 break-words text-body-ui text-ink">
            {child !== null && typeof child === 'object'
              ? <div className="border-l border-line pl-3"><PreviewValue value={child} /></div>
              : <PreviewValue value={child} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function MachinePublicSettings({ machine, makerspaceId }: {
  machine: Machine;
  makerspaceId: number;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const preview = useQuery({
    queryKey: machinePublicPreviewKey(machine.id),
    queryFn: () => getMachinePublicPreview(machine.id),
  });
  const publicity = useMutation({
    mutationFn: (isPublic: boolean) => setMachinePublicity(machine.id, isPublic),
    onSuccess: async (serverPreview, isPublic) => {
      notify.success(isPublic ? `${machine.name} is listed publicly` : `${machine.name} is hidden from the public listing`);
      queryClient.setQueryData<MachinePublicPreview>(
        machinePublicPreviewKey(machine.id),
        serverPreview,
      );
      queryClient.setQueryData<Machine>(machineKeys.detail(machine.id), (current) =>
        current ? { ...current, is_public: isPublic } : current,
      );
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
    onError: (error) => notify.failure("Couldn't change the public listing.", error),
  });

  return (
    <section className="grid gap-3">
      <SectionHeading as="h3" title="Public listing" />
      <Card padding="sm">
        <SwitchRow
          label="Show publicly"
          description="Retired machines remain hidden even when this setting is on."
          checked={machine.is_public}
          disabled={publicity.isPending}
          onCheckedChange={(checked) => publicity.mutate(checked)}
        />
      </Card>
      {publicity.error instanceof Error ? (
        <p className="text-caption text-danger-fg">{publicity.error.message}</p>
      ) : null}
      <div className="grid gap-3 rounded-lg bg-subtle p-4">
        <h4 className="text-label text-ink">What&apos;s shown publicly</h4>
        {preview.isLoading ? (
          <div className="grid gap-2" role="status" aria-label="Loading preview">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : null}
        {preview.error instanceof Error ? (
          <p className="text-caption text-danger-fg">{preview.error.message}</p>
        ) : null}
        {preview.data ? <PreviewValue value={preview.data} /> : null}
      </div>
    </section>
  );
}
