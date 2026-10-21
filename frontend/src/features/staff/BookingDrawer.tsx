import { useState } from "react";

import {
  Button,
  Callout,
  Card,
  Chip,
  ConfirmDialog,
  DangerZone,
  DetailDrawer,
  Dropdown,
  EmptyState,
  ErrorText,
  Field,
  Input,
  SectionHeading,
  Skeleton,
  StatusChip,
  useToast,
  type StatusTone,
} from "../../components/ui";
import { CustomAnswersView } from "../forms/CustomAnswersView";
import { BookableSpaceForm, valuesForSpace } from "./BookableSpaceForm";
import {
  useBookableSpace,
  useBookingAction,
  useDeactivateBookableSpace,
  useSpaceBookings,
  useUpdateBookableSpace,
  type Booking,
  type BookingAction,
  type BookingFilters,
  type BookingStatus,
} from "./bookingsApi";
import { PaymentReconcileActions } from "./PaymentReconcileActions";

type PendingAction = { booking: Booking; action: BookingAction };

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong.";
}

const BOOKING_TONES: Record<BookingStatus, StatusTone> = {
  pending: "warning",
  confirmed: "success",
  rejected: "danger",
  cancelled: "neutral",
  completed: "info",
  no_show: "danger",
};

const BOOKING_LABELS: Record<BookingStatus, string> = {
  pending: "Pending",
  confirmed: "Confirmed",
  rejected: "Rejected",
  cancelled: "Cancelled",
  completed: "Completed",
  no_show: "No-show",
};

function bookingTime(booking: Booking) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${format.format(new Date(booking.starts_at))} – ${format.format(new Date(booking.ends_at))}`;
}

function actionLabel(action: BookingAction) {
  return {
    approve: "Approve",
    reject: "Reject",
    cancel: "Cancel booking",
    complete: "Complete",
    "no-show": "Mark no-show",
  }[action];
}

function actionDone(action: BookingAction) {
  return {
    approve: "Booking approved",
    reject: "Booking rejected",
    cancel: "Booking cancelled",
    complete: "Booking completed",
    "no-show": "Marked as no-show",
  }[action];
}

export function BookingDrawer({ makerspaceId, spaceId, onClose }: {
  makerspaceId: number;
  spaceId: number;
  onClose: () => void;
}) {
  const spaceQuery = useBookableSpace(spaceId);
  const space = spaceQuery.data;
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<BookingFilters>({});
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const { showToast } = useToast();
  const bookings = useSpaceBookings(spaceId, filters, page);
  const update = useUpdateBookableSpace(makerspaceId, spaceId);
  const deactivate = useDeactivateBookableSpace(makerspaceId, spaceId);
  const action = useBookingAction(makerspaceId, spaceId);
  const failed = (error: unknown) => showToast(errorText(error), { tone: "error" });

  const setFilter = <K extends keyof BookingFilters>(key: K, value: BookingFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };
  const actionError = update.error || deactivate.error || action.error;
  const results = bookings.data?.results ?? [];

  return (
    <>
      <DetailDrawer open title={space?.name ?? "Space details"} onClose={onClose}>
        {spaceQuery.isLoading ? <Skeleton className="h-64 w-full" /> : null}
        {spaceQuery.error ? <EmptyState tone="error" title="Unable to load space" description={errorText(spaceQuery.error)} /> : null}
        {space ? (
          <div className="grid gap-6">
            <div className="flex flex-wrap items-center gap-2">
              <StatusChip tone={space.is_active ? "success" : "neutral"} size="sm">{space.is_active ? "Active" : "Inactive"}</StatusChip>
              <Chip tone="neutral" size="sm">{space.effective_requester_notifications_enabled ? "Requester emails on" : "Requester emails off"}</Chip>
            </div>
            {!space.is_active ? <Callout tone="info">This space is inactive and read-only.</Callout> : null}
            <BookableSpaceForm
              key={space.updated_at}
              initialValues={valuesForSpace(space)}
              onSubmit={(payload) => update.mutate(payload, { onSuccess: () => showToast("Space saved", { tone: "success" }), onError: failed })}
              pending={update.isPending}
              error={update.error ? errorText(update.error) : undefined}
              submitLabel="Save changes"
              disabled={!space.is_active}
            />
            <section aria-labelledby="space-bookings-title" className="grid gap-3">
              <SectionHeading
                as="h3"
                title={<span id="space-bookings-title">Bookings ({bookings.data?.count ?? 0})</span>}
                description="Contact details and custom answers are staff-only."
              />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-3">
                <Field label="Status">
                  <Dropdown value={filters.status ?? ""} onChange={(event) => setFilter("status", event.target.value as BookingFilters["status"])}>
                    <option value="">All statuses</option>
                    <option value="pending">Pending</option>
                    <option value="confirmed">Confirmed</option>
                    <option value="rejected">Rejected</option>
                    <option value="cancelled">Cancelled</option>
                    <option value="completed">Completed</option>
                    <option value="no_show">No-show</option>
                  </Dropdown>
                </Field>
                <Field label="Starts after">
                  <Input type="datetime-local" value={filters.starts_at ?? ""} onChange={(event) => setFilter("starts_at", event.target.value)} />
                </Field>
                <Field label="Ends before">
                  <Input type="datetime-local" value={filters.ends_at ?? ""} onChange={(event) => setFilter("ends_at", event.target.value)} />
                </Field>
              </div>
              {bookings.isLoading ? <Skeleton className="h-40 w-full" /> : null}
              <ErrorText message={bookings.error ? errorText(bookings.error) : null} />
              {bookings.data && !results.length ? <EmptyState title="No matching bookings" description="Bookings for this space will appear here. Clear the filters to see every booking." /> : null}
              {results.map((booking) => (
                <Card as="article" padding="sm" key={booking.id} className="grid gap-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h4 className="text-label text-ink">{booking.name}</h4>
                      <p className="mt-0.5 text-caption text-ink-muted">{bookingTime(booking)}</p>
                    </div>
                    <StatusChip tone={BOOKING_TONES[booking.status]} size="sm">{BOOKING_LABELS[booking.status]}</StatusChip>
                  </div>
                  <div className="text-body-ui">
                    <a className="block break-all text-ink-secondary hover:underline" href={"mailto:" + booking.email}>{booking.email}</a>
                    {booking.phone ? <a className="block text-ink-muted hover:underline" href={"tel:" + booking.phone}>{booking.phone}</a> : null}
                  </div>
                  <details className="rounded-md border border-line">
                    <summary className="cursor-pointer rounded-md px-3 py-2 text-label text-ink hover:bg-subtle">View custom answers</summary>
                    <div className="border-t border-line p-3"><CustomAnswersView snapshot={booking.custom_answers} /></div>
                  </details>
                  <PaymentReconcileActions
                    makerspaceId={makerspaceId}
                    payment={booking.payment}
                    invalidateKeys={[
                      ["booking-space", spaceId, "bookings"],
                      ["booking-space", spaceId],
                    ]}
                  />
                  <BookingActions booking={booking} onAction={(nextAction) => setPendingAction({ booking, action: nextAction })} />
                </Card>
              ))}
              {bookings.data && (bookings.data.previous || bookings.data.next) ? (
                <div className="flex flex-wrap items-center justify-end gap-2 text-body-ui text-ink-muted">
                  <span className="mr-auto tabular-nums">Page {page}</span>
                  <Button size="sm" disabled={!bookings.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
                  <Button size="sm" disabled={!bookings.data.next} onClick={() => setPage((value) => value + 1)}>Next</Button>
                </div>
              ) : null}
            </section>
            <ErrorText message={actionError ? errorText(actionError) : null} />
            {space.is_active ? (
              <DangerZone
                title="Deactivate space"
                description="The public page hides this space and no new bookings can be submitted or approved."
                action={<Button variant="danger" onClick={() => setConfirmDeactivate(true)}>Deactivate space…</Button>}
              />
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
      <ConfirmDialog
        open={pendingAction !== null}
        title={pendingAction ? actionLabel(pendingAction.action) : "Update booking"}
        message={pendingAction ? actionLabel(pendingAction.action) + " for " + pendingAction.booking.name + "?" : ""}
        confirmLabel={pendingAction ? actionLabel(pendingAction.action) : "Confirm"}
        tone={pendingAction?.action === "approve" || pendingAction?.action === "complete" ? "default" : "danger"}
        pending={action.isPending}
        onCancel={() => setPendingAction(null)}
        onConfirm={() => pendingAction && action.mutate({ bookingId: pendingAction.booking.id, action: pendingAction.action }, {
          onSuccess: () => { showToast(actionDone(pendingAction.action), { tone: "success" }); setPendingAction(null); },
          onError: (error) => { failed(error); setPendingAction(null); },
        })}
      />
      <ConfirmDialog
        open={confirmDeactivate}
        title="Deactivate space?"
        message="The public page will hide this space and no new bookings can be submitted or approved."
        confirmLabel="Deactivate"
        tone="danger"
        pending={deactivate.isPending}
        onCancel={() => setConfirmDeactivate(false)}
        onConfirm={() => deactivate.mutate(undefined, {
          onSuccess: () => { showToast("Space deactivated", { tone: "success" }); setConfirmDeactivate(false); },
          onError: (error) => { failed(error); setConfirmDeactivate(false); },
        })}
      />
    </>
  );
}

function BookingActions({ booking, onAction }: { booking: Booking; onAction: (action: BookingAction) => void }) {
  const ended = new Date(booking.ends_at) <= new Date();
  return (
    <div className="flex flex-wrap gap-2">
      {booking.status === "pending" ? <><Button size="sm" variant="success" onClick={() => onAction("approve")}>Approve…</Button><Button size="sm" variant="danger" onClick={() => onAction("reject")}>Reject…</Button></> : null}
      {booking.status === "confirmed" ? <Button size="sm" variant="danger" onClick={() => onAction("cancel")}>Cancel…</Button> : null}
      {booking.status === "confirmed" && ended ? <><Button size="sm" variant="success" onClick={() => onAction("complete")}>Complete…</Button><Button size="sm" variant="warn" onClick={() => onAction("no-show")}>No-show…</Button></> : null}
    </div>
  );
}
