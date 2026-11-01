import { useState } from "react";
import { useLocation } from "react-router-dom";

import { Button, ErrorBlock } from "../../../../components/ui";
import type { MachineServiceRequest, ServiceFile } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { getSessionGeneration } from "../../../../lib/apiSession";
import { useAuthActionOwner, type AuthAction } from "../../../auth/useAuthActionOwner";

function httpUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function ServiceRequestDetails({ makerspaceId, request }: { makerspaceId: number; request: MachineServiceRequest }) {
  const assigned = request.assigned_machine?.name ?? request.machine?.name;
  const source = httpUrl(request.source_link);
  const files = request.files ?? [];
  return (
    <div className="grid gap-2 text-body-ui text-ink-secondary">
      <p className="text-caption text-ink-muted">
        Job #{request.id} · {request.requester_name || request.requester?.display || request.requester?.username || "Unknown requester"}
        {assigned ? ` · ${assigned}` : " · Machine not assigned"}
      </p>
      {request.description || request.source_link || files.length ? (
        <details className="rounded-md border border-line p-3">
          <summary className="cursor-pointer font-medium text-ink">Project details &amp; files</summary>
          <div className="mt-3 grid gap-3">
            {request.description ? <p className="whitespace-pre-wrap break-words">{request.description}</p> : null}
            {source ? <a className="break-all underline" href={source} target="_blank" rel="noopener noreferrer">Open project source</a> : request.source_link ? <p>Project source link is unavailable: only HTTP(S) links can be opened.</p> : null}
            {files.length ? <ServiceFiles makerspaceId={makerspaceId} requestId={request.id} files={files} /> : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ServiceFiles(props: { makerspaceId: number; requestId: number; files: ServiceFile[] }) {
  const location = useLocation();
  // A new visit, session or attachment membership owns a fresh read intent, even A → B → A.
  const scope = `${props.makerspaceId}:${props.requestId}:${props.files.map((file) => file.id).sort((a, b) => a - b).join(",")}`;
  return <OwnedServiceFiles key={`${scope}:${getSessionGeneration()}:${location.key}`} scope={scope} {...props} />;
}

function OwnedServiceFiles({ scope, files }: { scope: string; files: ServiceFile[] }) {
  const owner = useAuthActionOwner(scope);
  const [viewing, setViewing] = useState<number | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [ready, setReady] = useState<{ fileId: number; url: string; action: AuthAction } | null>(null);
  async function view(fileId: number) {
    if (!files.some((file) => file.id === fileId) || !owner.isIntentCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    setViewing(fileId);
    setError(null);
    setReady(null);
    try {
      const result = await staffRequest<{ url: string }>(`/admin/machine-service/files/${fileId}/url`);
      if (!owner.isCurrent(action)) return;
      const url = httpUrl(result.url);
      if (!url) throw new Error("The file link is unavailable. Try opening it again.");
      // Keep the signed URL only in this mounted visit. A real link click preserves browser
      // user activation even when the API response takes longer than its popup allowance.
      setReady({ fileId, url, action });
    } catch (caught) {
      if (owner.isCurrent(action)) setError(caught instanceof Error ? caught : new Error("Couldn't open the file. Try again."));
    } finally {
      if (owner.isCurrent(action)) setViewing(null);
      owner.finish(action);
    }
  }
  return (
    <div className="grid gap-2">
      <ul className="grid gap-2" aria-label="Attached files">
        {files.map((file) => (
          <li key={file.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0 break-all">{file.original_filename}</span>
            <span className="flex flex-wrap gap-2">
              <Button size="sm" disabled={viewing !== null} loading={viewing === file.id} aria-label={`Get link for ${file.original_filename}`} onClick={() => void view(file.id)}>Get file link</Button>
              {ready && ready.fileId === file.id && owner.isCurrent(ready.action) ? (
                <Button asChild size="sm" variant="secondary">
                  <a href={ready.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${file.original_filename}`} onClick={(event) => {
                    if (!owner.isCurrent(ready.action)) event.preventDefault();
                  }}>Open file</a>
                </Button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <ErrorBlock error={error} />
      {ready && owner.isCurrent(ready.action) ? <p role="status" className="text-caption text-ink-muted">File link ready. Select Open file to view it. Get a new link if it expires.</p> : null}
      {error ? <p className="text-caption text-ink-muted">Use Get file link to retry.</p> : null}
    </div>
  );
}
