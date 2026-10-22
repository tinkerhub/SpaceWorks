import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, ErrorText, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText } from "./panels/shared";

export type EmailTestResult = {
  delivered: boolean;
  to: string;
  detail?: string;
  email_log_id: number;
};

/**
 * Sends one email to the signed-in staffer through the SAVED mail settings -- the same
 * path request and printing emails take -- and says plainly why it failed if it did.
 */
export function MakerspaceEmailTestSettings({ makerspaceId, unsaved }: { makerspaceId: number; unsaved: boolean }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const test = useMutation({
    mutationFn: () =>
      staffRequest<EmailTestResult>(`/admin/makerspace/${makerspaceId}/email-test`, { method: "POST" }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["email-logs", makerspaceId] });
      queryClient.invalidateQueries({ queryKey: ["integration-health", makerspaceId] });
      showToast(
        result.delivered ? `Test email sent to ${result.to}` : result.detail ?? "The test email wasn't sent",
        { tone: result.delivered ? "success" : "warning" },
      );
    },
    onError: (error) => showToast(errorText(error, "Couldn't send the test email"), { tone: "error" }),
  });

  return (
    <SettingsRow
      title="Test"
      description="Sends a test email to your own address through the saved settings, and records it in the email log."
    >
      <div className="grid gap-2">
        <div>
          <Button
            variant="secondary"
            size="sm"
            disabled={unsaved}
            loading={test.isPending}
            loadingLabel="Sending…"
            onClick={() => test.mutate()}
          >
            Send test email
          </Button>
        </div>
        {unsaved ? <p className="text-caption text-ink-muted">Save your changes before sending a test email.</p> : null}
        {test.data && !test.isPending ? (
          test.data.delivered ? (
            <Callout tone="success" role="status">Sent to {test.data.to}.</Callout>
          ) : (
            <Callout tone="danger" role="alert" title="Not sent">{test.data.detail ?? null}</Callout>
          )
        ) : null}
        <ErrorText message={test.error?.message} />
      </div>
    </SettingsRow>
  );
}
