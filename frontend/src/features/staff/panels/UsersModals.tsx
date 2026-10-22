import { Dropdown, Field, Input, Modal, PasswordInput, Textarea } from "../../../components/ui";
import { GeneralError, ModalActions, validationErrors } from "./usersModalParts";

export { CreateMakerspaceModal, ResetPasswordModal } from "./UsersAccountModals";

export type StaffForm = {
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  role_id: number | "";
  makerspace_id: string;
};
export type RestrictForm = { status: "restricted" | "suspended"; reason: string };
export type MakerspaceForm = {
  name: string;
  public_code: string;
  slug: string;
  location: string;
  superadmin_access_enabled: boolean;
};
export type ResetPasswordForm = { password: string };
export type ResetPasswordResult = { username: string; temporary_password: string };

export function AddStaffModal({
  open,
  form,
  makerspaceName,
  pending,
  error,
  roles,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  form: StaffForm;
  makerspaceName: string;
  pending: boolean;
  error: unknown;
  roles: { id: number; name: string }[];
  onChange: (form: StaffForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  // Password is required: the API does not return an auto-generated one, so a
  // blank password would create an account nobody can sign into.
  const disabled = pending || !form.username.trim() || !form.password || !form.role_id;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add staff"
      description={makerspaceName ? `They'll join ${makerspaceName} with the role you pick.` : undefined}
      footer={<ModalActions pending={pending} disabled={disabled} submitLabel="Add staff" onClose={onClose} onSubmit={onSubmit} />}
    >
      <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Username" error={errors.username}>
          <Input autoComplete="off" value={form.username} onChange={(event) => onChange({ ...form, username: event.target.value })} />
        </Field>
        <Field label="Email" optional error={errors.email}>
          <Input type="email" value={form.email} onChange={(event) => onChange({ ...form, email: event.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name" optional error={errors.first_name}>
            <Input value={form.first_name} onChange={(event) => onChange({ ...form, first_name: event.target.value })} />
          </Field>
          <Field label="Last name" optional error={errors.last_name}>
            <Input value={form.last_name} onChange={(event) => onChange({ ...form, last_name: event.target.value })} />
          </Field>
        </div>
        <Field label="Password" helperText="Share it with them securely. They can change it after signing in." error={errors.password}>
          <PasswordInput autoComplete="new-password" value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Role" error={errors.role_id}>
            <Dropdown value={String(form.role_id)} onChange={(event) => onChange({ ...form, role_id: Number(event.target.value) || "" })}>
              <option value="" disabled>Select a role</option>
              {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
            </Dropdown>
          </Field>
          <Field label="Makerspace">
            <Input readOnly value={makerspaceName} />
          </Field>
        </div>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}

export function RestrictUserModal({
  open,
  userLabel,
  form,
  pending,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  userLabel: string;
  form: RestrictForm;
  pending: boolean;
  error: unknown;
  onChange: (form: RestrictForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  const disabled = pending || !form.reason.trim();
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Restrict ${userLabel}?`}
      description="They keep their account but lose access until a platform admin restores it."
      size="sm"
      footer={<ModalActions pending={pending} disabled={disabled} submitLabel="Restrict access" submitVariant="danger" onClose={onClose} onSubmit={onSubmit} />}
    >
      <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Status" error={errors.status}>
          <Dropdown value={form.status} onChange={(event) => onChange({ ...form, status: event.target.value as RestrictForm["status"] })}>
            <option value="restricted">Restricted</option>
            <option value="suspended">Suspended</option>
          </Dropdown>
        </Field>
        <Field label="Reason" helperText="Recorded in the audit log." error={errors.reason}>
          <Textarea value={form.reason} onChange={(event) => onChange({ ...form, reason: event.target.value })} />
        </Field>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}
