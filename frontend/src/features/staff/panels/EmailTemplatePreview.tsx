import { Spinner } from "../../../components/ui";
import { cn } from "../../../lib/cn";

export type TemplatePreview = { subject: string; text_body: string; html_body: string };

/** The default copy a custom template replaces, for reference while editing. */
export function DefaultReference({ subject, text, typeOverride }: { subject: string; text: string; typeOverride: boolean }) {
  return (
    <div className="grid gap-4">
      <p className="text-body-ui text-ink-muted">
        {typeOverride ? "What this machine type sends when its override is off." : "What SpaceWorks sends when the custom template is off."}
      </p>
      <ReferenceBlock title="Subject" value={subject} />
      <ReferenceBlock title="Plain text" value={text} tall />
    </div>
  );
}

/** Server-rendered preview of the current draft with sample merge values. */
export function PreviewPane({ preview, loading, error }: { preview?: TemplatePreview; loading: boolean; error: Error | null }) {
  return (
    <div className="grid gap-4">
      <div className="flex min-h-6 items-center gap-2 text-caption text-ink-muted" aria-live="polite">
        {loading ? (
          <>
            <Spinner decorative className="size-4" />
            Updating preview…
          </>
        ) : (
          "Rendered with sample values. It updates as you type."
        )}
      </div>
      {error ? <p className="text-sm text-danger-fg" role="alert">{error.message}</p> : null}
      <ReferenceBlock title="Subject" value={preview?.subject ?? ""} />
      <ReferenceBlock title="Plain text" value={preview?.text_body ?? ""} tall />
      {preview?.html_body ? (
        <div className="grid gap-2">
          <h4 className="text-label text-ink">HTML</h4>
          <iframe className="h-96 w-full rounded-lg border border-line bg-white" sandbox="" srcDoc={preview.html_body} title="Rendered email HTML preview" />
        </div>
      ) : null}
    </div>
  );
}

function ReferenceBlock({ title, value, tall = false }: { title: string; value: string; tall?: boolean }) {
  return (
    <div className="grid gap-2">
      <h4 className="text-label text-ink">{title}</h4>
      <pre className={cn("overflow-auto whitespace-pre-wrap rounded-md border border-line bg-subtle p-3 font-mono text-xs text-ink-secondary", tall && "max-h-64")}>
        {value || "—"}
      </pre>
    </div>
  );
}
