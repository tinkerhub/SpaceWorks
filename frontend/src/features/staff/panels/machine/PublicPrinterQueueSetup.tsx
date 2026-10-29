import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ErrorBlock, Skeleton } from "../../../../components/ui";
import type { PublicPrinterQueueState as QueueState } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { useNotify } from "./machineUi";

export function PublicPrinterQueueSetup({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const notify = useNotify();
  const key = ["public-printer-queue-setup", makerspaceId];
  const path = `/admin/makerspaces/${makerspaceId}/machine-service/printer-queue`;
  const setup = useQuery({ queryKey: key, queryFn: () => staffRequest<QueueState>(path) });
  const enable = useMutation({
    mutationFn: () => staffRequest<QueueState>(path, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: async (state) => {
      client.setQueryData(key, state);
      notify.success("Public print requests enabled");
      await Promise.all([
        client.invalidateQueries({ queryKey: key }),
        client.invalidateQueries({ queryKey: ["public-printer-queues"] }),
      ]);
    },
    onError: (error) => notify.failure("Couldn't enable public print requests.", error),
  });
  return <div className="grid gap-2">
    {setup.isLoading ? <Skeleton className="h-10 w-full" /> : null}
    {setup.data?.enabled === false ? <>
      <p className="text-body-ui text-ink-muted">Public requests create a queue automatically when none exists. You can also prepare or reactivate a queue here.</p>
      <Button className="justify-self-start" loading={enable.isPending} onClick={() => enable.mutate()}>Enable public print requests</Button>
    </> : null}
    {setup.data?.enabled ? <p className="text-caption text-ink-muted">Public print queue ready · {setup.data.name}</p> : null}
    <ErrorBlock error={setup.error ?? enable.error} />
  </div>;
}
