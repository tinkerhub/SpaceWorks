import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, DetailDrawer, Field, Input, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { errorText } from "../panels/shared";
import { DialogError, submit } from "./shared";
import type { DialogProps } from "./types";

export function AssignBoxDialog({ row, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [boxCode, setBoxCode] = useState(row.assigned_box_code ?? "");
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/assign-box`, {
        method: "POST",
        body: JSON.stringify({ box_code: boxCode.trim() }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      showToast("Box assigned.", { tone: "success" });
      onClose();
    },
    onError: (failure) => showToast(errorText(failure, "Could not assign the box."), { tone: "error" }),
  });
  const close = () => {
    if (!mutation.isPending) onClose();
  };

  return (
    <DetailDrawer open title={`Assign box #${row.id}`} onClose={close}>
      <form
        className="grid gap-5"
        onSubmit={(event) => submit(event, () => {
          if (boxCode.trim()) mutation.mutate();
        })}
      >
        <Field label="Box QR code" helperText="Scan or type the code on the box the items go out in.">
          <Input className="font-mono" value={boxCode} onChange={(event) => setBoxCode(event.target.value)} autoFocus />
        </Field>
        <DialogError error={mutation.error} />
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={mutation.isPending} onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!boxCode.trim()} loading={mutation.isPending} loadingLabel="Assigning…">
            Assign box
          </Button>
        </div>
      </form>
    </DetailDrawer>
  );
}
