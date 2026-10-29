import type { Dispatch, FormEvent, ReactNode, SetStateAction } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { Button, Card, Dropdown, EmptyState, ErrorText, Field, Input, SectionHeading } from "../../components/ui";
import { FilePicker, TextArea, TextInput } from "./PublicPrintRequestParts";
import type { PublicFilamentPool } from "./publicApi";

export type FormState = {
  title: string;
  projectBrief: string;
  preferredSettings: string;
  consumablePoolId: string;
  estimatedFilamentGrams: string;
  material: string;
  color: string;
  // Raw text so the field can be emptied while typing; `printQuantity` clamps it.
  quantity: string;
  sourceLink: string;
};

export const initialForm: FormState = {
  title: "",
  projectBrief: "",
  preferredSettings: "",
  consumablePoolId: "",
  estimatedFilamentGrams: "",
  material: "",
  color: "",
  quantity: "1",
  sourceLink: "",
};

export function printQuantity(raw: string) {
  return Math.max(1, Math.floor(Number(raw)) || 1);
}

export function optional(value: string) {
  const trimmed = value.trim();
  return trimmed || undefined;
}

// Keep compatible public stock together by material, distinguished by color.
export function groupPoolsByMaterial(
  pools: PublicFilamentPool[],
): [string, PublicFilamentPool[]][] {
  const groups = new Map<string, PublicFilamentPool[]>();
  for (const pool of pools) {
    const key = pool.material || "Other";
    const bucket = groups.get(key);
    if (bucket) bucket.push(pool);
    else groups.set(key, [pool]);
  }
  return [...groups.entries()];
}

type PrintDetailsFormProps = {
  form: FormState;
  updateField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  poolsQuery: Pick<UseQueryResult<PublicFilamentPool[], Error>, "data" | "isSuccess" | "isLoading" | "isError" | "error">;
  mode?: "printer" | "generic";
  serviceLabels?: boolean;
  attachmentAccept?: string;
  modelFiles: File[];
  setModelFiles: Dispatch<SetStateAction<File[]>>;
  screenshotFiles: File[];
  setScreenshotFiles: Dispatch<SetStateAction<File[]>>;
  submitPending: boolean;
  identityReady?: boolean;
  identityStep?: ReactNode;
  submitError?: Error | null;
  uploadProgress: string;
  website: string;
  onWebsiteChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function PrintDetailsForm({
  form,
  updateField,
  poolsQuery,
  modelFiles,
  setModelFiles,
  screenshotFiles,
  setScreenshotFiles,
  submitPending,
  identityReady = true,
  identityStep,
  submitError,
  uploadProgress,
  website,
  onWebsiteChange,
  onSubmit,
  mode = "printer",
  serviceLabels = false,
  attachmentAccept = "",
}: PrintDetailsFormProps) {
  const noAvailablePools = poolsQuery.isSuccess && (poolsQuery.data?.length ?? 0) === 0;
  const unavailableSelection = Boolean(form.consumablePoolId)
    && !(poolsQuery.data ?? []).some((pool) => String(pool.id) === form.consumablePoolId);
  return (
    <Card className="@container">
      {identityStep ? <div className="mb-5">{identityStep}</div> : null}
      <SectionHeading title={serviceLabels ? "Service request" : "Print details"} description={serviceLabels ? "Describe your project. Staff will assign a machine. Files upload when you submit." : "Tell staff what to print. Files upload when you submit."} />
      <form className="mt-5 space-y-5" onSubmit={onSubmit}>
        {/* Honeypot: hidden from humans; bots that autofill it trigger the server decoy. */}
        <input
          aria-hidden="true"
          autoComplete="off"
          className="hidden"
          name="website"
          tabIndex={-1}
          value={website}
          onChange={(event) => onWebsiteChange(event.target.value)}
        />
        <fieldset className="min-w-0 space-y-5" disabled={submitPending || !identityReady}>
          <TextInput label="Title" maxLength={200} required value={form.title} onChange={(value) => updateField("title", value)} />
          <TextArea label={mode === "printer" ? "Project brief" : "Description"} optional value={form.projectBrief} onChange={(value) => updateField("projectBrief", value)} />
          {mode === "printer" ? <>
          <TextArea
            label="Slicer settings / personal preferences"
            optional
            value={form.preferredSettings}
            onChange={(value) => updateField("preferredSettings", value)}
          />
          <div className="grid gap-5 @min-[36rem]:grid-cols-2">
            <div className="grid gap-1.5">
              <Field
                label="Filament / material"
                helperText={poolsQuery.isLoading ? "Loading filament…" : undefined}
                error={poolsQuery.isError ? poolsQuery.error?.message : undefined}
              >
                <Dropdown value={form.consumablePoolId} onChange={(event) => updateField("consumablePoolId", event.target.value)}>
                  <option value="">No preference</option>
                  {unavailableSelection ? <option value={form.consumablePoolId} disabled>Selected filament unavailable</option> : null}
                  {groupPoolsByMaterial(poolsQuery.data ?? []).flatMap(([material, pools]) =>
                    pools.map((pool) => (
                      <option key={pool.id} value={pool.id}>
                        {`${material} · ${pool.color || "Default color"}`}
                      </option>
                    )),
                  )}
                </Dropdown>
              </Field>
              {noAvailablePools ? <EmptyState
                title="No filament currently available"
                description="There is no filament available to choose right now. You can still submit without a preference, and staff will confirm the options."
              /> : null}
            </div>
            <Field label="Quantity">
              <Input
                min={1}
                step={1}
                required
                type="number"
                value={form.quantity}
                onChange={(event) => updateField("quantity", event.target.value)}
                onBlur={() => updateField("quantity", String(printQuantity(form.quantity)))}
              />
            </Field>
            <Field label="Estimated filament (g)" optional helperText="If you know it from your slicer. Staff can adjust this.">
              <Input
                min={0}
                max={999999.99}
                step="0.01"
                type="number"
                value={form.estimatedFilamentGrams}
                onChange={(event) => updateField("estimatedFilamentGrams", event.target.value)}
              />
            </Field>
          </div>
          </> : null}
          <TextInput label="Source link" type="url" maxLength={200} optional value={form.sourceLink} onChange={(value) => updateField("sourceLink", value)} />
          {mode === "printer" ? (
          <div className="grid gap-5 @min-[36rem]:grid-cols-2">
            <FilePicker
              accept=".stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf"
              files={modelFiles}
              label="Model, CAD, or toolpath files"
              setFiles={setModelFiles}
            />
            <FilePicker
              accept="image/*,application/pdf"
              files={screenshotFiles}
              label="Estimated print-time screenshots (Bambu Lab)"
              setFiles={setScreenshotFiles}
            />
          </div>
          ) : attachmentAccept ? <FilePicker accept={attachmentAccept} files={modelFiles} label="Attachments" setFiles={setModelFiles} /> : null}
        </fieldset>

        {uploadProgress ? <p className="text-body-ui text-ink-muted" aria-live="polite">{uploadProgress}</p> : null}
        {submitError ? <ErrorText message={submitError.message} /> : null}
        <Button
          variant="primary"
          type="submit"
          fullWidth
          disabled={!form.title.trim() || !identityReady || submitPending}
          loading={submitPending}
          loadingLabel="Submitting…"
        >
          {serviceLabels ? "Submit service request" : "Submit print request"}
        </Button>
      </form>
    </Card>
  );
}
