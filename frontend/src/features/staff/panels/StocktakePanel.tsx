import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import {
  Button, DetailDrawer, Dialog, Dropdown, EmptyState, ErrorText, Field, Input, Pagination, SkeletonRows,
  Table, TBody, TD, TH, THead, TR, useToast,
} from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { errorText, Panel, StatusWord, type Makerspace, useStaffGet } from "./shared";
import { CountSection, type ContainerOption, type StocktakeRow } from "./StocktakeCountSection";
import { invalidateInventoryViews } from "../queryInvalidation";

// can_approve / can_apply are computed by the server for the signed-in user (manage_makerspace,
// and not the person who completed the count), so the buttons match what the API accepts.
const COLUMNS = ["ID", "Status", "Notes", "Container", ""];

const ACTION_TOAST: Record<string, [string, string]> = {
  complete: ["Count completed", "Could not complete the count"],
  approve: ["Stocktake approved", "Could not approve the stocktake"],
  "apply-adjustments": ["Adjustments applied", "Could not apply the adjustments"],
};

export function StocktakePanel({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [openId, setOpenId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createNotes, setCreateNotes] = useState("Cycle count");
  const [createContainerId, setCreateContainerId] = useState("");
  const stocktakes = usePaginatedQuery<StocktakeRow>({
    key: ["stocktakes", makerspace.id],
    path: `/admin/makerspace/${makerspace.id}/stocktakes`,
    resetKey: String(makerspace.id),
  });
  const containers = useStaffGet<{ results: ContainerOption[] }>(["stocktake-containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const containerName = (id: number) => containers.data?.results.find((container) => container.id === id)?.label ?? `Container #${id}`;
  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${makerspace.id}/stocktakes`, {
        method: "POST",
        body: JSON.stringify({ notes: createNotes, container_id: createContainerId ? Number(createContainerId) : null }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
      setCreateOpen(false);
      showToast("Stocktake started", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Could not start the stocktake"), { tone: "error" }),
  });
  const action = useMutation({
    mutationFn: (path: string) => staffRequest(path, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (_data, path) => {
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
      // The detail (status, lines) changes on every transition, not just on a new count.
      queryClient.invalidateQueries({ queryKey: ["stocktake-detail"] });
      if (path.endsWith("/apply-adjustments")) {
        invalidateInventoryViews(queryClient, makerspace.id);
        queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      }
      showToast(ACTION_TOAST[path.split("/").pop() ?? ""]?.[0] ?? "Stocktake updated", { tone: "success" });
    },
    onError: (error, path) => showToast(errorText(error, ACTION_TOAST[path.split("/").pop() ?? ""]?.[1] ?? "Could not update the stocktake"), { tone: "error" }),
  });
  const actionError = action.error instanceof Error ? action.error.message : undefined;
  const rows = stocktakes.results;

  return (
    <Panel
      title="Stocktake"
      description="Count what is on the shelves, review the variance, then apply the adjustments."
      actions={<Button variant="primary" startIcon={<Plus />} onClick={() => setCreateOpen(true)}>Start stocktake</Button>}
    >
      <div className="grid gap-4">
        {actionError ? <ErrorText message={actionError} /> : null}
        {stocktakes.error instanceof Error ? <ErrorText message={stocktakes.error.message} /> : null}
        {!stocktakes.isLoading && !stocktakes.error && !rows.length ? (
          <EmptyState
            title="No stocktakes yet"
            description="Start one to count a container or the whole makerspace."
            action={<Button onClick={() => setCreateOpen(true)}>Start stocktake</Button>}
          />
        ) : (
          <Table label="Stocktakes" className="min-w-[680px]">
            <THead><tr>{COLUMNS.map((column, index) => <TH key={index}>{column || <span className="sr-only">Actions</span>}</TH>)}</tr></THead>
            <TBody>
              {stocktakes.isLoading ? <SkeletonRows rows={4} cols={COLUMNS.length} /> : rows.map((row) => (
                <TR key={row.id}>
                  <TD className="whitespace-nowrap font-mono">#{row.id}</TD>
                  <TD><StatusWord status={row.status} tone={row.status === "approved" ? "success" : row.status === "counting" ? "info" : undefined} /></TD>
                  <TD className="text-ink-secondary"><span className="block max-w-64 break-words">{row.notes || "-"}</span></TD>
                  <TD className="text-ink-secondary">{row.container ? containerName(row.container) : "All containers"}</TD>
                  <TD>
                    <div className="flex flex-wrap justify-end gap-2">
                      {canCount(row.status) ? <Button size="sm" onClick={() => setOpenId(row.id)}>Count items</Button> : null}
                      {row.status === "counting" ? (
                        <Button size="sm" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/complete`)}>Complete</Button>
                      ) : null}
                      {row.can_approve ? (
                        <Button size="sm" variant="success" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/approve`)}>Approve</Button>
                      ) : null}
                      {row.can_apply ? (
                        <Button size="sm" variant="success" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/apply-adjustments`)}>Apply</Button>
                      ) : null}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        <Pagination page={stocktakes.page} totalPages={stocktakes.totalPages} onChange={stocktakes.setPage} count={stocktakes.count} pageSize={stocktakes.pageSize} />
      </div>

      <DetailDrawer open={openId !== null} title={openId ? `Count stocktake #${openId}` : "Count stocktake"} onClose={() => setOpenId(null)}>
        {openId ? <CountSection key={openId} makerspace={makerspace} stocktakeId={openId} /> : null}
      </DetailDrawer>

      <Dialog
        open={createOpen}
        onClose={() => { if (!create.isPending) setCreateOpen(false); }}
        title="Start stocktake"
        description="Counts start from the expected quantities on record."
        footer={(
          <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
            <Button disabled={create.isPending} onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="stocktake-create-form" loading={create.isPending} loadingLabel="Starting…">Start stocktake</Button>
          </div>
        )}
      >
        <form id="stocktake-create-form" className="grid gap-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <Field label="Session notes">
            <Input value={createNotes} onChange={(event) => setCreateNotes(event.target.value)} />
          </Field>
          <Field label="Container">
            <Dropdown value={createContainerId} onChange={(event) => setCreateContainerId(event.target.value)}>
              <option value="">All containers</option>
              {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
            </Dropdown>
          </Field>
          {create.isError ? <ErrorText message={create.error.message} /> : null}
        </form>
      </Dialog>
    </Panel>
  );
}

function canCount(status: string) {
  return status === "draft" || status === "counting";
}
