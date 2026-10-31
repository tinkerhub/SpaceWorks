import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../../components/ui";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import { PrintDetailsForm, initialForm, optional, printQuantity, type FormState } from "../printing/PublicPrintRequestForm";
import { uploadPrintFilesBounded, type PublicPrintUploadItem } from "../printing/PublicPrintUploads";
import { uploadToStorage } from "../printing/publicApi";
import { presignServiceUpload, submitServiceRequest, type ServiceIdentity, type ServiceType } from "./publicApi";
import { saveRequestCapability, type CapabilityOutcome } from "../requests/requestCapabilities";
import { serviceTypesKey } from "./useServiceTypes";

type Props = {
  slug: string;
  type: ServiceType;
  identity: ServiceIdentity;
  identityReady: boolean;
  identityStep?: ReactNode;
  isVisitCurrent?: () => boolean;
  onPendingChange: (pending: boolean, action: AuthAction) => void;
  onSuccess: (token: string, persistence?: CapabilityOutcome) => void;
};
type Snapshot = {
  action: AuthAction;
  slug: string;
  body: Parameters<typeof submitServiceRequest>[1];
  requester: ServiceIdentity;
  typeId: number;
  printer: boolean;
  policy: ServiceType["file_policy"];
  invalidPool: boolean;
  files: PublicPrintUploadItem[];
  isVisitCurrent: () => boolean;
  complete: Props["onSuccess"];
  release: Props["onPendingChange"];
};

export function ServiceRequestForm(props: Props) {
  const scope = JSON.stringify([props.slug, props.type.id, props.type.is_printer,
    props.identityReady, props.identity.checkin_mid, props.identity.name]);
  const owner = useAuthActionOwner(scope);
  // Remount private fields before paint, including a later return to the same person/type.
  return <ServiceRequestDraft key={JSON.stringify([scope, owner.context.epoch])} {...props} owner={owner} />;
}

function ServiceRequestDraft({ slug, type, identity, identityReady, identityStep, isVisitCurrent = () => true,
  onPendingChange, onSuccess, owner }: Props & { owner: ReturnType<typeof useAuthActionOwner> }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [form, setForm] = useState<FormState>(initialForm);
  const [modelFiles, setModelFiles] = useState<File[]>([]);
  const [screenshotFiles, setScreenshotFiles] = useState<File[]>([]);
  const [website, setWebsite] = useState("");
  const [uploadProgress, setUploadProgress] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const admitted = useRef<Snapshot | null>(null);

  function isCurrent(snapshot: Snapshot) { return owner.isCurrent(snapshot.action) && snapshot.isVisitCurrent(); }
  function requireCurrent(snapshot: Snapshot) {
    if (!isCurrent(snapshot)) throw new Error("This service submission is no longer current.");
  }
  function release(snapshot: Snapshot) {
    if (admitted.current !== snapshot) return;
    admitted.current = null;
    owner.finish(snapshot.action);
    // The parent matches this exact action, even when the form has disappeared.
    snapshot.release(false, snapshot.action);
  }
  useLayoutEffect(() => () => {
    if (admitted.current) release(admitted.current);
  }, []);

  const submit = useMutation({
    mutationFn: async (snapshot: Snapshot) => {
      requireCurrent(snapshot);
      const { files, policy } = snapshot;
      if (snapshot.invalidPool) {
        throw new Error("Your selected filament is no longer available. Please choose again.");
      }
      for (const { file } of files) {
        if (file.size > policy.max_bytes) {
          throw new Error(`${file.name} exceeds the ${Math.floor(policy.max_bytes / 1024 / 1024)} MB file limit.`);
        }
        if (!snapshot.printer && !policy.allowed_extensions.some((extension) =>
          file.name.toLowerCase().endsWith(extension.startsWith(".") ? extension.toLowerCase() : `.${extension.toLowerCase()}`),
        )) throw new Error(`${file.name} is not an allowed attachment type.`);
      }
      let queueId: number | undefined;
      const fileIds = await uploadPrintFilesBounded(files, async ({ file, kind }) => {
        requireCurrent(snapshot);
        const staged = await presignServiceUpload(snapshot.slug, {
          machine_type_id: snapshot.typeId, queue_id: queueId, kind,
          filename: file.name, content_type: file.type || "application/octet-stream", ...snapshot.requester,
        });
        requireCurrent(snapshot);
        if (!Number.isInteger(staged.queue_id) || staged.queue_id <= 0 || (queueId !== undefined && queueId !== staged.queue_id)) {
          throw new Error("The upload queue changed. Please submit again.");
        }
        queueId = staged.queue_id;
        requireCurrent(snapshot);
        await uploadToStorage({ ...staged.upload, fields: staged.upload.fields ?? {} }, file);
        requireCurrent(snapshot);
        return staged.file_id;
      }, (message) => { if (isCurrent(snapshot)) setUploadProgress(message); }, 1);
      // Serial uploads pin the first queue; even the no-file path checks before dispatch.
      requireCurrent(snapshot);
      return submitServiceRequest(snapshot.slug, { ...snapshot.body, queue_id: queueId, file_ids: fileIds });
    },
    onSuccess: (response, snapshot) => {
      if (!isCurrent(snapshot)) return;
      const persistence = saveRequestCapability(snapshot.slug, "machine", response.public_token);
      queryClient.invalidateQueries({ queryKey: serviceTypesKey(snapshot.slug) });
      queryClient.invalidateQueries({ queryKey: ["public-service-status", snapshot.slug, response.public_token] });
      setForm(initialForm);
      setModelFiles([]);
      setScreenshotFiles([]);
      setWebsite("");
      snapshot.complete(response.public_token, persistence);
      showToast("Service request submitted", { tone: "success" });
    },
    onError: (failure, snapshot) => {
      if (!isCurrent(snapshot)) return;
      setError(failure);
      showToast("Service request wasn't submitted", { tone: "error" });
    },
    onSettled: (_data, _error, snapshot) => {
      if (isCurrent(snapshot)) { setUploadProgress(""); setPending(false); }
      release(snapshot);
    },
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
    submitPending={pending} submitError={error} uploadProgress={uploadProgress}
    identityReady={identityReady} identityStep={identityStep}
    website={website} onWebsiteChange={setWebsite}
    onSubmit={(event) => {
      event.preventDefault();
      if (!form.title.trim() || !identityReady || !isVisitCurrent()) return;
      // Synchronous admission closes the same-tick gap before React paints pending.
      const action = owner.begin();
      if (!action) return;
      const pool = type.consumable_pools.find((option) => String(option.id) === form.consumablePoolId);
      const snapshot: Snapshot = {
        action, slug, requester: { ...identity }, typeId: type.id, printer: type.is_printer,
        policy: { ...type.file_policy, allowed_extensions: [...type.file_policy.allowed_extensions],
          allowed_mimes: [...type.file_policy.allowed_mimes] },
        invalidPool: Boolean(form.consumablePoolId && !pool), isVisitCurrent, complete: onSuccess, release: onPendingChange,
        files: [
          ...modelFiles.map((file) => ({ file, kind: type.is_printer ? "stl" as const : "attachment" as const })),
          ...(type.is_printer ? screenshotFiles.map((file) => ({ file, kind: "screenshot" as const })) : []),
        ],
        body: {
          machine_type_id: type.id, title: form.title.trim(), source_link: optional(form.sourceLink), website, ...identity,
          ...(type.is_printer ? {
            project_brief: optional(form.projectBrief),
            preferred_settings: form.preferredSettings.trim() ? { notes: form.preferredSettings.trim() } : undefined,
            consumable_pool_id: pool?.id ?? null, material: pool?.material, color: pool?.color,
            estimated_filament_grams: form.estimatedFilamentGrams.trim() || null,
            quantity: printQuantity(form.quantity),
          } : { description: optional(form.projectBrief) }),
        },
      };
      admitted.current = snapshot;
      setPending(true);
      setError(null);
      onPendingChange(true, action);
      submit.mutate(snapshot);
    }}
  />;
}
