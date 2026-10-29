import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../../components/ui";
import { PrintDetailsForm, initialForm, optional, printQuantity, type FormState } from "../printing/PublicPrintRequestForm";
import { uploadPrintFilesBounded, type PublicPrintUploadItem } from "../printing/PublicPrintUploads";
import { uploadToStorage } from "../printing/publicApi";
import { presignServiceUpload, submitServiceRequest, type ServiceIdentity, type ServiceType } from "./publicApi";
import { serviceTypesKey } from "./useServiceTypes";

type Props = {
  slug: string;
  type: ServiceType;
  identity: ServiceIdentity;
  identityReady: boolean;
  identityStep?: ReactNode;
  onPendingChange: (pending: boolean) => void;
  onSuccess: (token: string) => void;
};

export function ServiceRequestForm({ slug, type, identity, identityReady, identityStep, onPendingChange, onSuccess }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [form, setForm] = useState<FormState>(initialForm);
  const [modelFiles, setModelFiles] = useState<File[]>([]);
  const [screenshotFiles, setScreenshotFiles] = useState<File[]>([]);
  const [website, setWebsite] = useState("");
  const [uploadProgress, setUploadProgress] = useState("");

  const submit = useMutation({
    // Snapshot all inputs before the first await. This child is keyed by type ID.
    mutationFn: async (snapshot: { form: FormState; files: PublicPrintUploadItem[]; identity: ServiceIdentity; website: string; type: ServiceType }) => {
      const { form: draft, files, identity: requester, website: trap, type: selected } = snapshot;
      const pool = selected.consumable_pools.find((option) => String(option.id) === draft.consumablePoolId);
      if (draft.consumablePoolId && !pool) {
        throw new Error("Your selected filament is no longer available. Please choose again.");
      }
      for (const { file } of files) {
        if (file.size > selected.file_policy.max_bytes) {
          throw new Error(`${file.name} exceeds the ${Math.floor(selected.file_policy.max_bytes / 1024 / 1024)} MB file limit.`);
        }
        if (!selected.is_printer && !selected.file_policy.allowed_extensions.some((extension) =>
          file.name.toLowerCase().endsWith(extension.startsWith(".") ? extension.toLowerCase() : `.${extension.toLowerCase()}`),
        )) throw new Error(`${file.name} is not an allowed attachment type.`);
      }
      let queueId: number | undefined;
      const fileIds = await uploadPrintFilesBounded(files, async ({ file, kind }) => {
        const staged = await presignServiceUpload(slug, {
          machine_type_id: selected.id, queue_id: queueId, kind,
          filename: file.name, content_type: file.type || "application/octet-stream", ...requester,
        });
        if (!Number.isInteger(staged.queue_id) || staged.queue_id <= 0 || (queueId !== undefined && queueId !== staged.queue_id)) {
          throw new Error("The upload queue changed. Please submit again.");
        }
        queueId = staged.queue_id;
        await uploadToStorage({ ...staged.upload, fields: staged.upload.fields ?? {} }, file);
        return staged.file_id;
      }, setUploadProgress, 1); // The first response pins every subsequent upload to its queue.
      return submitServiceRequest(slug, {
        machine_type_id: selected.id, queue_id: queueId, title: draft.title.trim(),
        source_link: optional(draft.sourceLink), file_ids: fileIds, website: trap, ...requester,
        ...(selected.is_printer ? {
          project_brief: optional(draft.projectBrief),
          preferred_settings: draft.preferredSettings.trim() ? { notes: draft.preferredSettings.trim() } : undefined,
          consumable_pool_id: pool?.id ?? null, material: pool?.material, color: pool?.color,
          estimated_filament_grams: draft.estimatedFilamentGrams.trim() || null,
          quantity: printQuantity(draft.quantity),
        } : { description: optional(draft.projectBrief) }),
      });
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: serviceTypesKey(slug) });
      queryClient.invalidateQueries({ queryKey: ["public-service-status", slug, response.public_token] });
      setForm(initialForm);
      setModelFiles([]);
      setScreenshotFiles([]);
      onSuccess(response.public_token);
      showToast("Service request submitted", { tone: "success" });
    },
    onError: () => showToast("Service request wasn't submitted", { tone: "error" }),
    onSettled: () => { setUploadProgress(""); onPendingChange(false); },
  });

  return <PrintDetailsForm
    mode={type.is_printer ? "printer" : "generic"}
    serviceLabels
    attachmentAccept={type.file_policy.allowed_extensions.map((extension) => extension.startsWith(".") ? extension : `.${extension}`).join(",")}
    form={form}
    updateField={(key, value) => setForm((current) => ({ ...current, [key]: value }))}
    poolsQuery={{ data: type.consumable_pools, isSuccess: true, isLoading: false, isError: false, error: null }}
    modelFiles={modelFiles} setModelFiles={setModelFiles}
    screenshotFiles={screenshotFiles} setScreenshotFiles={setScreenshotFiles}
    submitPending={submit.isPending} submitError={submit.error} uploadProgress={uploadProgress}
    identityReady={identityReady} identityStep={identityStep}
    website={website} onWebsiteChange={setWebsite}
    onSubmit={(event) => {
      event.preventDefault();
      if (!form.title.trim() || !identityReady || submit.isPending) return;
      onPendingChange(true);
      submit.mutate({
        form: { ...form }, type, identity: { ...identity }, website,
        files: [
          ...modelFiles.map((file) => ({ file, kind: type.is_printer ? "stl" as const : "attachment" as const })),
          ...(type.is_printer ? screenshotFiles.map((file) => ({ file, kind: "screenshot" as const })) : []),
        ],
      });
    }}
  />;
}
