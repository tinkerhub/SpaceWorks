import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, Callout, CheckboxField, ErrorText, useToast } from "../../components/ui";

export type RecoveryState = {
  mode: "normal" | "quiesced" | "quarantined";
  quarantine_reason: string;
  quarantined_at: string | null;
  residual_risk: string;
};

export function RecoveryQuarantinePanel({ state, onAcknowledged }: { state: RecoveryState; onAcknowledged: (state: RecoveryState) => void }) {
  const { showToast } = useToast();
  const [confirmed, setConfirmed] = useState(false);
  const acknowledge = useMutation({
    mutationFn: () => staffRequest<RecoveryState>("/recovery", {
      method: "POST",
      body: JSON.stringify({ acknowledgement: state.residual_risk }),
    }),
    onSuccess: (next) => {
      showToast("Quarantine lifted", { tone: "success" });
      onAcknowledged(next);
    },
    onError: () => showToast("Quarantine not lifted", { tone: "error" }),
  });
  return (
    <AuthLayout kicker="Recovery quarantine" title="Authority is suspended" description={state.quarantine_reason}>
      <div className="flex flex-col gap-5">
        <Callout tone="danger" title="Residual risk">
          {state.residual_risk}
        </Callout>
        {/* The checkbox is the confirmation: lifting sends the exact statement shown above. */}
        <CheckboxField
          checked={confirmed}
          onCheckedChange={(value) => setConfirmed(value === true)}
          label="I reviewed the restore report where one exists and accept this exact residual risk."
        />
        <Button
          variant="danger"
          fullWidth
          disabled={!confirmed}
          loading={acknowledge.isPending}
          loadingLabel="Lifting…"
          onClick={() => acknowledge.mutate()}
        >
          Lift quarantine
        </Button>
        <ErrorText message={acknowledge.error?.message} />
      </div>
    </AuthLayout>
  );
}
