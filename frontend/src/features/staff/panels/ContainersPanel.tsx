import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import {
  Button, CheckboxField, DetailDrawer, Dialog, EmptyState, ErrorText, Field, Input, SearchInput, SkeletonRows,
  StatusChip, Table, TBody, TD, TH, THead, TR, Textarea, useToast,
} from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateContainerViews } from "../queryInvalidation";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";
import { ContainerDetail, type Container } from "./ContainersPanelDetail";

const COLUMNS = ["Container", "Code", "Location", "Status", ""];

// Containers had list + create (in QR tools) but no edit/move/contents/history surface in
// React - they were only manageable in the Django admin. This panel wires the operations
// container endpoints (MANAGE_QR for create/edit/move, VIEW_INVENTORY for contents/history).
// The tab itself is gated on MANAGE_QR, so every viewer here may create and edit.
export function ContainersPanel({ makerspace, canEditInventory }: { makerspace: Makerspace; canEditInventory: boolean }) {
  const containers = useStaffGet<{ results: Container[] }>(["containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Container | "new" | null>(null);
  const [viewing, setViewing] = useState<Container | null>(null);
  const term = search.trim().toLowerCase();
  const rows = useMemo(
    () => (containers.data?.results ?? []).filter((box) => !term || [box.label, box.code, box.location].some((value) => value?.toLowerCase().includes(term))),
    [containers.data?.results, term],
  );
  const hasAny = Boolean(containers.data?.results?.length);

  return (
    <Panel
      title="Containers"
      description="Boxes, shelves and bins that hold stock. Each one gets its own QR."
      actions={<Button variant="primary" startIcon={<Plus />} onClick={() => setEditing("new")}>New container</Button>}
    >
      <div className="grid gap-4">
        {hasAny ? (
          <div className="max-w-md">
            <SearchInput aria-label="Search containers" placeholder="Search by name, code or location" value={search} onChange={(event) => setSearch(event.target.value)} onClear={() => setSearch("")} />
          </div>
        ) : null}
        {containers.error instanceof Error ? <ErrorText message={containers.error.message} /> : null}
        {!containers.isLoading && !containers.error && !rows.length ? (
          hasAny
            ? <EmptyState title="No containers match" description="Try another name, code or location." action={<Button onClick={() => setSearch("")}>Clear search</Button>} />
            : <EmptyState title="No containers yet" description="Create one for each box or shelf, then print its QR label." action={<Button onClick={() => setEditing("new")}>New container</Button>} />
        ) : !containers.error ? (
          <Table label="Containers" className="min-w-[640px]">
            <THead><tr>{COLUMNS.map((column, index) => <TH key={index}>{column || <span className="sr-only">Actions</span>}</TH>)}</tr></THead>
            <TBody>
              {containers.isLoading ? <SkeletonRows rows={4} cols={COLUMNS.length} /> : rows.map((box) => (
                <TR key={box.id}>
                  <TD className="font-semibold"><span className="block max-w-64 break-words">{box.label}</span></TD>
                  <TD className="font-mono text-ink-secondary">{box.code || "-"}</TD>
                  <TD className="text-ink-secondary">{box.location || "-"}</TD>
                  <TD>{box.is_active === false ? <StatusChip tone="warning" size="sm">Inactive</StatusChip> : <StatusChip tone="success" size="sm">Active</StatusChip>}</TD>
                  <TD>
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button size="sm" onClick={() => setViewing(box)}>Contents</Button>
                      <Button size="sm" variant="quiet" onClick={() => setEditing(box)}>Edit</Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
      </div>

      <DetailDrawer open={Boolean(viewing)} title={viewing?.label ?? "Container"} onClose={() => setViewing(null)}>
        {viewing ? <ContainerDetail key={viewing.id} container={viewing} canEditInventory={canEditInventory} /> : null}
      </DetailDrawer>
      {editing ? (
        <ContainerFormDialog
          key={editing === "new" ? "new" : editing.id}
          makerspaceId={makerspace.id}
          container={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </Panel>
  );
}

function ContainerFormDialog({ makerspaceId, container, onClose }: { makerspaceId: number; container: Container | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [label, setLabel] = useState(container?.label ?? "");
  const [location, setLocation] = useState(container?.location ?? "");
  const [description, setDescription] = useState(container?.description ?? "");
  const [isActive, setIsActive] = useState(container?.is_active ?? true);
  const isNew = !container;

  const save = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({ label: label.trim(), location: location.trim(), description: description.trim(), is_active: isActive });
      return container
        ? staffRequest<Container>(`/admin/containers/${container.id}/move`, { method: "POST", body })
        : staffRequest<Container>(`/admin/makerspace/${makerspaceId}/containers`, { method: "POST", body });
    },
    onSuccess: (saved) => {
      invalidateContainerViews(queryClient, makerspaceId, container?.id ?? saved?.id);
      showToast(isNew ? "Container created" : "Container saved", { tone: "success" });
      onClose();
    },
    onError: (error) => showToast(errorText(error, isNew ? "Could not create the container" : "Could not save the container"), { tone: "error" }),
  });

  return (
    <Dialog
      open
      onClose={() => { if (!save.isPending) onClose(); }}
      title={container ? `Edit ${container.label}` : "New container"}
      description={isNew ? "A QR code is created for it automatically." : undefined}
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={save.isPending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="container-form" disabled={!label.trim()} loading={save.isPending} loadingLabel="Saving…">
            {isNew ? "Create container" : "Save"}
          </Button>
        </div>
      )}
    >
      <form id="container-form" className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (label.trim()) save.mutate(); }}>
        <Field label="Label"><Input value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
        <Field label="Location" optional><Input value={location} placeholder="Shelf B3" onChange={(event) => setLocation(event.target.value)} /></Field>
        <Field label="Description" optional><Textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
        <CheckboxField label="Active" description="Untick to retire a container while keeping its history." checked={isActive} onCheckedChange={(checked) => setIsActive(checked === true)} />
        {save.isError ? <ErrorText message={save.error.message} /> : null}
      </form>
    </Dialog>
  );
}
