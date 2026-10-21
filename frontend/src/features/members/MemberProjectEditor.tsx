import { Plus, Trash2 } from "lucide-react";

import { Button, Field, Input, Textarea } from "../../components/ui";
import { ImageUploader } from "../staff/ImageUploader";

export type ProjectDraft = {
  id?: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
};

/** One project in the maker-profile form. Edits stay local until the profile is saved. */
export function ProjectEditor({
  makerspaceId,
  project,
  imageUrl,
  onChange,
  onRemove,
  onImageChanged,
}: {
  makerspaceId: number;
  project: ProjectDraft;
  imageUrl: string | null;
  onChange: (next: ProjectDraft) => void;
  onRemove: () => void;
  onImageChanged: () => void;
}) {
  const editLink = (index: number, changes: Partial<{ label: string; url: string }>) =>
    onChange({
      ...project,
      links: project.links.map((row, position) => (position === index ? { ...row, ...changes } : row)),
    });

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-subtle p-4">
      <Field label="Project title" hideLabel>
        <Input
          placeholder="Project title"
          value={project.title}
          onChange={(event) => onChange({ ...project, title: event.target.value })}
        />
      </Field>
      <Field label="Project description" hideLabel>
        <Textarea
          rows={2}
          placeholder="What is it?"
          value={project.description}
          onChange={(event) => onChange({ ...project, description: event.target.value })}
        />
      </Field>
      {/* An image can only be attached to a project that exists server-side — a new one
          has no id to attach it to, so it appears after the first save. */}
      {project.id ? (
        <ImageUploader
          endpoint={`/member/makerspaces/${makerspaceId}/profile/image`}
          currentUrl={imageUrl}
          label="Project image"
          extraBody={{ project_id: project.id }}
          clearQuery={`?project_id=${project.id}`}
          onChanged={onImageChanged}
        />
      ) : (
        <p className="text-caption text-ink-muted">Save the project to add an image.</p>
      )}
      {project.links.length ? (
        <div className="flex flex-col gap-2">
          {project.links.map((link, index) => (
            <div key={index} className="flex flex-col gap-2 sm:flex-row">
              <Field label="Link label" hideLabel className="sm:w-44">
                <Input placeholder="Label" value={link.label} onChange={(event) => editLink(index, { label: event.target.value })} />
              </Field>
              <Field label="Link URL" hideLabel className="flex-1">
                <Input placeholder="https://…" value={link.url} onChange={(event) => editLink(index, { url: event.target.value })} />
              </Field>
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          startIcon={<Plus />}
          onClick={() => onChange({ ...project, links: [...project.links, { label: "", url: "" }] })}
        >
          Add link
        </Button>
        <Button size="sm" variant="danger-quiet" startIcon={<Trash2 />} onClick={onRemove}>
          Remove project
        </Button>
      </div>
    </div>
  );
}
