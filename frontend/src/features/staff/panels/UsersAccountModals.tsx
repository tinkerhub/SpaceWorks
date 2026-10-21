import { useEffect, useState } from "react";
import { Copy } from "lucide-react";

import { Button, CheckboxField, Field, Input, Modal, PasswordInput } from "../../../components/ui";
import type { MakerspaceForm, ResetPasswordForm, ResetPasswordResult } from "./UsersModals";
import { GeneralError, ModalActions, validationErrors } from "./usersModalParts";

export function CreateMakerspaceModal({
  open,
  form,
  pending,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  form: MakerspaceForm;
  pending: boolean;
  error: unknown;
  onChange: (form: MakerspaceForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  const disabled = pending || !form.name.trim() || !form.public_code.trim() || !form.slug.trim();
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create makerspace"
      footer={<ModalActions pending={pending} disabled={disabled} submitLabel="Create makerspace" onClose={onClose} onSubmit={onSubmit} />}
    >
      <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Name" error={errors.name}>
          <Input value={form.name} onChange={(event) => onChange({ ...form, name: event.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Public code" helperText="Up to 4 letters, used on QR labels." error={errors.public_code}>
            <Input className="font-mono" maxLength={4} value={form.public_code} onChange={(event) => onChange({ ...form, public_code: event.target.value.toUpperCase() })} />
          </Field>
          <Field label="Slug" helperText="Part of its web address." error={errors.slug}>
            <Input className="font-mono" value={form.slug} onChange={(event) => onChange({ ...form, slug: event.target.value })} />
          </Field>
        </div>
        <Field label="Location" optional error={errors.location}>
          <Input value={form.location} onChange={(event) => onChange({ ...form, location: event.target.value })} />
        </Field>
        <div className="grid gap-1.5 rounded-lg border border-line bg-subtle p-4">
          <CheckboxField
            checked={form.superadmin_access_enabled}
            onCheckedChange={(checked) => onChange({ ...form, superadmin_access_enabled: checked === true })}
            label="Superadmin can access this makerspace"
            description="Untick for a collaborating makerspace that should stay out of your reports and admin views. Only their admin can turn it back on."
          />
          {errors.superadmin_access_enabled ? <span className="text-caption text-danger-fg">{errors.superadmin_access_enabled}</span> : null}
        </div>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}

export function ResetPasswordModal({
  open,
  userLabel,
  form,
  pending,
  error,
  result,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  userLabel: string;
  form: ResetPasswordForm;
  pending: boolean;
  error: unknown;
  result: ResetPasswordResult | null;
  onChange: (form: ResetPasswordForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const errors = validationErrors(error);
  const hasShortPassword = form.password.length > 0 && form.password.length < 8;
  const disabled = pending || hasShortPassword;

  useEffect(() => {
    setCopied(false);
  }, [open, result?.temporary_password]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reset password for ${userLabel}`}
      size="sm"
      footer={
        result ? (
          <div className="flex justify-end">
            <Button variant="primary" onClick={onClose}>Done</Button>
          </div>
        ) : (
          <ModalActions pending={pending} disabled={disabled} submitLabel="Reset password" onClose={onClose} onSubmit={onSubmit} />
        )
      }
    >
      {result ? (
        <div className="grid gap-3">
          <p className="text-body-ui text-ink-secondary">Share this with them securely. It won&apos;t be shown again.</p>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-subtle p-3">
            <code className="break-all font-mono text-base font-semibold text-ink">{result.temporary_password}</code>
            <Button
              size="sm"
              startIcon={<Copy />}
              onClick={() => {
                void navigator.clipboard.writeText(result.temporary_password).then(() => setCopied(true));
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      ) : (
        <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
          <p className="text-body-ui text-ink-secondary">
            We&apos;ll set a temporary password. They must change it the next time they sign in. You can do this again any time.
          </p>
          <Field
            label="Temporary password"
            optional
            helperText="Leave blank to generate one."
            error={errors.password ?? (hasShortPassword ? "Use at least 8 characters, or leave it blank to generate one." : undefined)}
          >
            <PasswordInput
              minLength={8}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => onChange({ ...form, password: event.target.value })}
            />
          </Field>
          <GeneralError error={error} errors={errors} />
        </form>
      )}
    </Modal>
  );
}
