import { Button, Field, Input, Modal, useToast } from "../../components/ui";
import type { ApiClientCreateResponse } from "./apiClientsApi";

/** The client secret is shown once, right after create or rotate, with a copy button. */
export function ApiClientSecretDialog({ secret, onClose }: {
  secret: ApiClientCreateResponse | null;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      showToast("Secret copied", { tone: "success" });
    } catch {
      showToast("Couldn't copy. Select the secret and copy it by hand.", { tone: "error" });
    }
  };
  return (
    <Modal
      open={Boolean(secret)}
      onClose={onClose}
      title="Copy this secret now"
      description="It won't be shown again. Store it somewhere safe before you close this."
      size="md"
      footer={secret ? (
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={() => void copy(secret.client_secret)}>Copy</Button>
          <Button variant="primary" onClick={onClose}>Done</Button>
        </div>
      ) : null}
    >
      {secret ? (
        <div className="grid gap-4">
          <Field label="Client ID">
            <Input readOnly value={secret.client_id} className="font-mono text-sm" />
          </Field>
          <Field label="Client secret">
            <Input readOnly value={secret.client_secret} className="font-mono text-sm" onFocus={(event) => event.currentTarget.select()} />
          </Field>
        </div>
      ) : null}
    </Modal>
  );
}
