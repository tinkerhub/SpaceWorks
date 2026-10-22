import { useState } from "react";
import { Plus } from "lucide-react";

import { Button, Callout, Chip, DataTable, ErrorText, Modal, StatusChip, useToast, type DataTableColumn } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { BookableSpaceForm } from "./BookableSpaceForm";
import { BookingDrawer } from "./BookingDrawer";
import { useBookableSpaces, useCreateBookableSpace, type BookableSpace } from "./bookingsApi";
import { Panel, errorText } from "./panels/shared";

const KIND_LABELS: Record<BookableSpace["kind"], string> = {
  dev_room: "Development room",
  bench: "Bench",
  meeting: "Meeting room",
  other: "Other",
};

const DESCRIPTION = "Spaces people can book, their public settings, forms and booking requests.";

const columns = (onOpen: (id: number) => void): DataTableColumn<BookableSpace>[] => [
  {
    key: "name",
    header: "Space",
    sortable: true,
    render: (space) => (
      <button
        type="button"
        className="grid rounded-md text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        onClick={() => onOpen(space.id)}
      >
        <span className="text-label text-ink underline-offset-4 hover:underline">{space.name}</span>
        <span className="text-caption text-ink-muted">{space.location || "No location label"}</span>
      </button>
    ),
  },
  { key: "kind", header: "Type", render: (space) => KIND_LABELS[space.kind] ?? space.kind.replace("_", " ") },
  { key: "approval_mode", header: "Approval", render: (space) => space.approval_mode === "approve" ? "Staff approval" : "Instant" },
  { key: "is_public", header: "Public", render: (space) => <Chip tone={space.is_public ? "info" : "neutral"} size="sm">{space.is_public ? "Public" : "Private"}</Chip> },
  { key: "is_active", header: "Status", render: (space) => <StatusChip tone={space.is_active ? "success" : "neutral"} size="sm">{space.is_active ? "Active" : "Inactive"}</StatusChip> },
];

export function BookingsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { showToast } = useToast();
  const spaces = useBookableSpaces(makerspaceId, page);
  const create = useCreateBookableSpace(makerspaceId);
  const apiError = spaces.error instanceof StructuredApiError ? spaces.error : null;

  if (apiError?.status === 403) {
    return <Panel title="Bookings" description={DESCRIPTION}><Callout tone="info">Only Space Managers can manage bookings.</Callout></Panel>;
  }
  if (apiError?.status === 400) {
    return <Panel title="Bookings" description={DESCRIPTION}><Callout tone="info">The Bookings module is not enabled for this makerspace.</Callout></Panel>;
  }

  return (
    <Panel
      title="Bookings"
      description={DESCRIPTION}
      actions={<Button variant="primary" startIcon={<Plus />} onClick={() => setCreateOpen(true)}>Create space</Button>}
    >
      <div className="grid gap-4">
        {spaces.error ? <ErrorText message={spaces.error.message} /> : null}
        <DataTable
          columns={columns(setSelectedId)}
          data={spaces.data?.results ?? []}
          loading={spaces.isLoading}
          skeletonCols={5}
          emptyTitle="No bookable spaces"
          emptyDescription="Create a space to start accepting bookings."
          emptyAction={<Button onClick={() => setCreateOpen(true)}>Create space</Button>}
        />
        {spaces.data && (spaces.data.previous || spaces.data.next) ? (
          <div className="flex flex-wrap items-center justify-end gap-2 text-body-ui text-ink-muted">
            <span className="mr-auto tabular-nums">Page {page} · {spaces.data.count} total</span>
            <Button size="sm" disabled={!spaces.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
            <Button size="sm" disabled={!spaces.data.next} onClick={() => setPage((value) => value + 1)}>Next</Button>
          </div>
        ) : null}
      </div>
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create bookable space"
        size="xl"
        footer={<div className="flex justify-end"><Button disabled={create.isPending} onClick={() => setCreateOpen(false)}>Cancel</Button></div>}
      >
        <BookableSpaceForm
          onSubmit={(payload) => create.mutate(payload, {
            onSuccess: (space) => {
              setCreateOpen(false);
              setSelectedId(space.id);
              showToast("Space created", { tone: "success" });
            },
            onError: (error) => showToast(errorText(error, "Couldn't create the space"), { tone: "error" }),
          })}
          pending={create.isPending}
          error={create.error?.message}
          submitLabel="Create space"
        />
      </Modal>
      {selectedId !== null ? <BookingDrawer key={selectedId} makerspaceId={makerspaceId} spaceId={selectedId} onClose={() => setSelectedId(null)} /> : null}
    </Panel>
  );
}
