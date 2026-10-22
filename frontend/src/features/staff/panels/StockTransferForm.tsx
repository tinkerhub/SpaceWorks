import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { Button, Callout, Dialog, Dropdown, ErrorText, Field, IconButton, Input, SectionHeading, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { errorText, type Makerspace, type Product, useStaffGet } from "./shared";
import { invalidateContainerViews, invalidateInventoryViews } from "../queryInvalidation";

type ListResponse<T> = { count?: number; results: T[] };
export type Container = { id: number; code?: string; label: string; location?: string };
type LineDraft = { key: number; productId: string; quantity: string };

const firstLine = (): LineDraft[] => [{ key: 1, productId: "", quantity: "1" }];

// Name first: the code is a 32-character opaque token that people neither read nor type, so
// leading with it pushed the container's name off the end of every option and table cell.
export function labelForContainer(container: Container) {
  return [container.label, container.location].filter(Boolean).join(" · ") || container.code || `Container #${container.id}`;
}

/**
 * "New transfer" dialog. The source/destination makerspace ids live in the panel
 * because the transfer list below follows the chosen source.
 */
export function NewTransferDialog({
  open,
  onClose,
  isSuperadmin,
  spaceOptions,
  sourceMakerspaceId,
  destinationMakerspaceId,
  onSourceChange,
  onDestinationChange,
}: {
  open: boolean;
  onClose: () => void;
  isSuperadmin: boolean;
  spaceOptions: Makerspace[];
  sourceMakerspaceId: number;
  destinationMakerspaceId: number;
  onSourceChange: (id: number) => void;
  onDestinationChange: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [sourceContainerId, setSourceContainerId] = useState("");
  const [destinationContainerId, setDestinationContainerId] = useState("");
  const [reason, setReason] = useState("");
  const [lineRows, setLineRows] = useState<LineDraft[]>(firstLine);
  const [nextLineKey, setNextLineKey] = useState(2);
  const [validationError, setValidationError] = useState("");

  const resetDraft = () => {
    setSourceContainerId("");
    setDestinationContainerId("");
    setLineRows(firstLine());
    setNextLineKey(2);
    setValidationError("");
  };
  // A new source makerspace invalidates every container and product choice.
  useEffect(() => resetDraft(), [sourceMakerspaceId]);

  const products = useStaffGet<ListResponse<Product>>(["inventory", sourceMakerspaceId], `/admin/makerspace/${sourceMakerspaceId}/inventory?page_size=1000`);
  const sourceContainers = useStaffGet<ListResponse<Container>>(["containers", sourceMakerspaceId], `/admin/makerspace/${sourceMakerspaceId}/containers?page_size=1000`);
  const destinationContainers = useStaffGet<ListResponse<Container>>(["containers", destinationMakerspaceId], `/admin/makerspace/${destinationMakerspaceId}/containers?page_size=1000`);
  const isCrossMakerspace = destinationMakerspaceId !== sourceMakerspaceId;

  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${sourceMakerspaceId}/stock-transfers`, {
        method: "POST",
        body: JSON.stringify({
          // Cross-makerspace transfers ignore the source container (and the control is
          // disabled), so never send a stale value the backend would otherwise record.
          source_container_id: isCrossMakerspace || !sourceContainerId ? null : Number(sourceContainerId),
          // destination_container_id is resolved within the destination makerspace
          // (same makerspace for intra-transfers), so it is valid in both modes.
          destination_container_id: destinationContainerId ? Number(destinationContainerId) : null,
          destination_makerspace_id: isCrossMakerspace ? destinationMakerspaceId : null,
          reason: reason.trim(),
          lines: lineRows.map((line) => ({ product_id: Number(line.productId), quantity: Number(line.quantity) })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers", sourceMakerspaceId] });
      invalidateInventoryViews(queryClient, sourceMakerspaceId);
      invalidateContainerViews(queryClient, sourceMakerspaceId, sourceContainerId ? Number(sourceContainerId) : undefined);
      if (isCrossMakerspace) {
        queryClient.invalidateQueries({ queryKey: ["transfers", destinationMakerspaceId] });
        invalidateInventoryViews(queryClient, destinationMakerspaceId);
      }
      invalidateContainerViews(queryClient, destinationMakerspaceId, destinationContainerId ? Number(destinationContainerId) : undefined);
      resetDraft();
      setReason("");
      showToast("Transfer created", { tone: "success" });
      onClose();
    },
    onError: (error) => showToast(errorText(error, "Could not create the transfer"), { tone: "error" }),
  });

  const updateLine = (key: number, patch: Partial<LineDraft>) =>
    setLineRows((rows) => rows.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  const addLine = () => {
    setLineRows((rows) => [...rows, { key: nextLineKey, productId: "", quantity: "1" }]);
    setNextLineKey((key) => key + 1);
  };

  const submit = () => {
    const invalidQuantity = lineRows.some((line) => !Number.isInteger(Number(line.quantity)) || Number(line.quantity) < 1);
    if (!reason.trim()) setValidationError("Reason is required.");
    else if (!lineRows.length) setValidationError("Add at least one transfer line.");
    else if (lineRows.some((line) => !line.productId)) setValidationError("Choose a product for every line.");
    else if (invalidQuantity) setValidationError("Quantities must be whole numbers of at least 1.");
    else {
      setValidationError("");
      create.mutate();
    }
  };

  const loadErrors = [products.error, sourceContainers.error, destinationContainers.error].filter((error): error is Error => error instanceof Error);

  return (
    <Dialog
      open={open}
      onClose={() => { if (!create.isPending) onClose(); }}
      title="New transfer"
      description="Move available stock to another container or makerspace."
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={create.isPending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="stock-transfer-form" loading={create.isPending} loadingLabel="Creating…">Create transfer</Button>
        </div>
      )}
    >
      <form id="stock-transfer-form" className="grid gap-5" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <div className="grid gap-4 md:grid-cols-2">
          {isSuperadmin ? (
            <>
              <Field label="Source makerspace">
                <Dropdown value={String(sourceMakerspaceId)} onChange={(event) => onSourceChange(Number(event.target.value))}>
                  {spaceOptions.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
                </Dropdown>
              </Field>
              <Field label="Destination makerspace">
                <Dropdown value={String(destinationMakerspaceId)} onChange={(event) => { onDestinationChange(Number(event.target.value)); setDestinationContainerId(""); }}>
                  {spaceOptions.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
                </Dropdown>
              </Field>
            </>
          ) : null}
          <Field label="Source container" helperText={isCrossMakerspace ? "Ignored for makerspace-to-makerspace transfers." : undefined}>
            <Dropdown value={sourceContainerId} disabled={isCrossMakerspace || sourceContainers.isLoading} onChange={(event) => setSourceContainerId(event.target.value)}>
              <option value="">Any source container</option>
              {sourceContainers.data?.results?.map((box) => <option key={box.id} value={box.id}>{labelForContainer(box)}</option>)}
            </Dropdown>
          </Field>
          <Field label="Destination container">
            <Dropdown value={destinationContainerId} disabled={destinationContainers.isLoading} onChange={(event) => setDestinationContainerId(event.target.value)}>
              <option value="">No destination container</option>
              {destinationContainers.data?.results?.map((box) => <option key={box.id} value={box.id}>{labelForContainer(box)}</option>)}
            </Dropdown>
          </Field>
        </div>

        <div className="grid gap-3">
          <SectionHeading as="h3" title="Transfer lines" action={<Button size="sm" startIcon={<Plus />} onClick={addLine}>Add line</Button>} />
          {lineRows.map((line, index) => (
            <div key={line.key} className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_120px_auto]">
              <Field label={`Product for transfer line ${index + 1}`}>
                <Dropdown value={line.productId} disabled={products.isLoading} onChange={(event) => updateLine(line.key, { productId: event.target.value })}>
                  <option value="">Choose a product</option>
                  {products.data?.results?.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.available_quantity} available)</option>)}
                </Dropdown>
              </Field>
              <Field label={`Quantity for transfer line ${index + 1}`}>
                <Input min={1} inputMode="numeric" type="number" value={line.quantity} onChange={(event) => updateLine(line.key, { quantity: event.target.value })} />
              </Field>
              <IconButton label={`Remove transfer line ${index + 1}`} variant="danger" onClick={() => setLineRows((rows) => rows.filter((row) => row.key !== line.key))}>
                <X />
              </IconButton>
            </div>
          ))}
        </div>

        <Field label="Reason">
          <Input value={reason} placeholder="Why is this stock moving?" onChange={(event) => setReason(event.target.value)} />
        </Field>
        {isCrossMakerspace ? (
          <Callout tone="info" title="Makerspace-to-makerspace transfer">
            The quantity is deducted here and credited to a matching product in the destination makerspace (created there if
            needed, kept private until it opts in). Only available stock can move; individually tracked products are not supported.
          </Callout>
        ) : null}
        <ErrorText message={validationError} />
        {create.isError ? <ErrorText message={create.error.message} /> : null}
        {loadErrors.map((error, index) => <ErrorText key={index} message={error.message} />)}
      </form>
    </Dialog>
  );
}
