import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { MakerspaceArchiveRequest } from "../../generated/api";
import { Button, ConfirmDialog, DangerZone, ErrorText, Field, Skeleton, StatusChip, Textarea, useToast } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";

const REASON_MAX_LENGTH = 2000;

const ERROR_MESSAGES: Record<string, string> = {
  pending_archive_request_exists: "An archive request is already pending for this makerspace.",
  archive_request_cooldown: "Please wait one hour after the last archive request before filing another.",
  superadmin_access_disabled: "Turn on superadmin access before requesting archival.",
  makerspace_already_archived: "This makerspace has already been archived.",
  archive_request_not_pending: "This archive request is no longer pending and cannot be withdrawn.",
};

type Props = {
  makerspaceId: number;
  canManageMakerspace: boolean;
};

export function MakerspaceArchiveRequestPanel({ makerspaceId, canManageMakerspace }: Props) {
  if (!canManageMakerspace) return null;
  return <AuthorizedArchiveRequestPanel makerspaceId={makerspaceId} />;
}

function AuthorizedArchiveRequestPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const queryKey = ["staff", "archive-requests", makerspaceId] as const;
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const requests = useQuery({
    queryKey,
    queryFn: () => staffRequest<MakerspaceArchiveRequest[]>(
      `/admin/makerspace/${makerspaceId}/archive-requests`,
    ),
  });

  const create = useMutation({
    mutationFn: (value: string) => staffRequest<MakerspaceArchiveRequest>(
      `/admin/makerspace/${makerspaceId}/archive-requests`,
      { method: "POST", body: JSON.stringify({ reason: value }) },
    ),
    onSuccess: () => {
      setReason("");
      setFormError("");
      queryClient.invalidateQueries({ queryKey });
      showToast("Archive request filed. A superadmin will review it.", { tone: "success" });
    },
    onError: (error) => showToast(errorMessage(error), { tone: "error" }),
    onSettled: () => setConfirming(false),
  });
  const withdraw = useMutation({
    mutationFn: (requestId: number) => staffRequest<MakerspaceArchiveRequest>(
      `/admin/makerspace/${makerspaceId}/archive-requests/${requestId}/withdraw`,
      { method: "POST" },
    ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      showToast("Archive request withdrawn", { tone: "success" });
    },
    onError: (error) => showToast(errorMessage(error), { tone: "error" }),
  });

  const pending = requests.data?.find((request) => request.status === "pending");
  const history = requests.data?.filter((request) => request.status !== "pending") ?? [];
  const actionError = create.error ?? withdraw.error;

  return (
    <DangerZone
      title={<span id="archive-request-title">Archive this makerspace</span>}
      description={(
        <>
          Filing a request does not archive anything. A superadmin must confirm it first. Once
          archived, this makerspace disappears from the staff console and you lose access to it,
          so the outcome will arrive by email.
        </>
      )}
    >
      <div className="mt-4 grid min-w-0 gap-4">
        {requests.isLoading ? <Skeleton className="h-24 w-full" /> : null}
        {requests.isError ? <ErrorText message={errorMessage(requests.error)} /> : null}

        {requests.isSuccess && pending ? (
          <div className="rounded-md border border-line bg-subtle p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="text-label text-ink">Pending request</h4>
                <StatusChip tone="warning" size="sm">Pending</StatusChip>
              </div>
              <Button
                variant="secondary"
                size="sm"
                loading={withdraw.isPending}
                loadingLabel="Withdrawing…"
                onClick={() => withdraw.mutate(pending.id)}
              >
                Withdraw
              </Button>
            </div>
            <p className="mt-3 whitespace-pre-wrap text-body-ui text-ink">{pending.reason}</p>
            <p className="mt-2 text-caption text-ink-muted">
              Filed by {pending.requested_by_username ?? "a staff member"} on{" "}
              <time dateTime={pending.requested_at}>{formatDateTime(pending.requested_at)}</time>
            </p>
          </div>
        ) : null}

        {requests.isSuccess && !pending ? (
          <form
            className="grid max-w-3xl gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!reason.trim()) {
                setFormError("Enter a reason for requesting archival.");
                return;
              }
              setFormError("");
              setConfirming(true);
            }}
          >
            <Field
              label="Reason for archival"
              id="archive-request-reason"
              error={formError || undefined}
              helperText={(
                <span className="flex flex-wrap justify-between gap-2">
                  <span>Do not include personal data.</span>
                  <span>{reason.length} / {REASON_MAX_LENGTH}</span>
                </span>
              )}
            >
              <Textarea
                value={reason}
                required
                maxLength={REASON_MAX_LENGTH}
                rows={5}
                onChange={(event) => {
                  setReason(event.target.value);
                  setFormError("");
                  create.reset();
                }}
              />
            </Field>
            <div>
              <Button variant="danger" type="submit" disabled={create.isPending}>
                Request archival…
              </Button>
            </div>
          </form>
        ) : null}

        {actionError ? (
          <p className="text-body-ui text-danger-fg" role="alert">{errorMessage(actionError)}</p>
        ) : null}

        {requests.isSuccess ? (
          <div className="border-t border-line pt-4">
            <h4 className="text-label text-ink">Resolved history</h4>
            {history.length === 0 ? (
              <p className="mt-2 text-body-ui text-ink-muted">No resolved archive requests.</p>
            ) : (
              <ul className="mt-3 grid gap-3">
                {history.map((request) => <HistoryRow key={request.id} request={request} />)}
              </ul>
            )}
          </div>
        ) : null}
      </div>
      <ConfirmDialog
        open={confirming}
        title="File an archive request?"
        message="A superadmin reviews it before anything is archived. Once archived, you lose access to this makerspace."
        confirmLabel="File request"
        tone="danger"
        pending={create.isPending}
        onConfirm={() => create.mutate(reason.trim())}
        onCancel={() => setConfirming(false)}
      />
    </DangerZone>
  );
}

function HistoryRow({ request }: { request: MakerspaceArchiveRequest }) {
  const label = request.status[0].toUpperCase() + request.status.slice(1);
  const tone = request.status === "approved" ? "success" : request.status === "declined" ? "danger" : "neutral";
  return (
    <li className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={tone} size="sm">{label}</StatusChip>
        <span className="text-caption text-ink-muted">
          Requested by {request.requested_by_username ?? "a staff member"} on {formatDateTime(request.requested_at)}
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-body-ui text-ink">{request.reason}</p>
      {request.resolution_note.trim() ? (
        <p className="mt-2 text-body-ui text-ink-muted">Resolution note: {request.resolution_note}</p>
      ) : null}
      {request.resolved_at ? (
        <p className="mt-2 text-caption text-ink-muted">
          Resolved by {request.resolved_by_username ?? "a superadmin"} on {formatDateTime(request.resolved_at)}
        </p>
      ) : null}
    </li>
  );
}

function errorMessage(error: unknown) {
  if (error instanceof StructuredApiError) {
    if (error.code && ERROR_MESSAGES[error.code]) return ERROR_MESSAGES[error.code];
    return error.detail ?? error.message;
  }
  return error instanceof Error ? error.message : "Unable to update archive requests.";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
