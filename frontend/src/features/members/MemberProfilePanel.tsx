import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Plus } from "lucide-react";

import { Button, CheckboxField, ErrorText, Field, Input, SectionHeading, Spinner, Textarea, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { AccountCard } from "../account/AccountCard";
import { ImageUploader } from "../staff/ImageUploader";
import { ProjectEditor, type ProjectDraft } from "./MemberProjectEditor";

export type MemberProject = {
  id: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
  image_url: string | null;
};

export interface MemberProfileActivity {
  events_attended?: number;
  events_registered?: number;
  recent_attended_events?: { id: number; title: string; starts_at: string }[];
}

export type MemberProfile = {
  membership_id: number;
  display_name: string;
  is_visible: boolean;
  show_attended_events: boolean;
  headline: string;
  institution: string;
  bio: string;
  avatar_url: string | null;
  interests: string[];
  languages: string[];
  education: { institution: string; qualification?: string; year?: string }[];
  github_username: string;
  github_contributions: number | null;
  projects: MemberProject[];
  activity: MemberProfileActivity;
};

const tagsToText = (values: string[]) => values.join(", ");
const textToTags = (value: string) =>
  value.split(",").map((item) => item.trim()).filter(Boolean);

/**
 * The member's own profile: what they choose to show the rest of their makerspace.
 *
 * Editing is a single form that PUTs the whole thing, projects included — the API
 * replaces the project list rather than merging it, because with a merge there is no
 * way to express deleting one.
 */
export function MemberProfilePanel({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const profile = useQuery({
    queryKey: ["member", "profile-page", makerspaceId],
    queryFn: () => staffRequest<MemberProfile>(`/member/makerspaces/${makerspaceId}/profile`),
    retry: false,
  });
  const [draft, setDraft] = useState<MemberProfile | null>(null);
  const [interests, setInterests] = useState("");
  const [languages, setLanguages] = useState("");
  const [projects, setProjects] = useState<ProjectDraft[]>([]);
  // Set by any edit, cleared by a successful save. Guards the re-seed effect below.
  const [dirty, setDirty] = useState(false);

  // Seed once, then only re-seed when the form has no unsaved edits.
  //
  // An image upload invalidates this query, so a naive "re-seed on every snapshot" reset
  // every field to the last saved copy — a member who wrote a bio and then changed their
  // avatar lost the bio with no warning. Image URLs are the one thing that must still
  // refresh after an upload, so they are merged in separately below.
  useEffect(() => {
    if (!profile.data || dirty) return;
    setDraft(profile.data);
    setInterests(tagsToText(profile.data.interests));
    setLanguages(tagsToText(profile.data.languages));
    setProjects(profile.data.projects.map((project) => ({ ...project })));
  }, [profile.data, dirty]);

  useEffect(() => {
    if (!profile.data || !dirty) return;
    // Dirty form: keep every edited field, but take the new image URLs, since those
    // changed on the server and are not editable here.
    const server = profile.data;
    setDraft((current) => (current ? { ...current, avatar_url: server.avatar_url, projects: server.projects } : current));
  }, [profile.data, dirty]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<MemberProfile>(`/member/makerspaces/${makerspaceId}/profile`, {
        method: "PUT",
        body: JSON.stringify({
          is_visible: draft?.is_visible ?? false,
          show_attended_events: draft?.show_attended_events ?? false,
          headline: draft?.headline ?? "",
          institution: draft?.institution ?? "",
          bio: draft?.bio ?? "",
          github_username: draft?.github_username ?? "",
          interests: textToTags(interests),
          languages: textToTags(languages),
          education: draft?.education ?? [],
          projects: projects
            .filter((project) => project.title.trim())
            .map((project) => ({
              ...(project.id ? { id: project.id } : {}),
              title: project.title.trim(),
              description: project.description,
              links: project.links.filter((link) => link.label.trim() && link.url.trim()),
            })),
        }),
      }),
    onSuccess: () => {
      showToast("Profile saved", { tone: "success" });
      setDirty(false);
      return client.invalidateQueries({ queryKey: ["member", "profile-page", makerspaceId] });
    },
    onError: () => showToast("Profile not saved", { tone: "error" }),
  });

  if (profile.isLoading) {
    return <AccountCard title="Your maker profile" description={<span className="inline-flex items-center gap-2"><Spinner decorative className="size-4" />Loading your profile…</span>} />;
  }
  if (!draft) return null;

  const patch = (changes: Partial<MemberProfile>) => {
    setDirty(true);
    setDraft({ ...draft, ...changes });
  };
  const editProjects = (next: ProjectDraft[]) => {
    setDirty(true);
    setProjects(next);
  };
  const refreshImages = () => client.invalidateQueries({ queryKey: ["member", "profile-page", makerspaceId] });

  return (
    <AccountCard
      title="Your maker profile"
      description="Nothing here is shown to other members until you publish it."
    >
      {/* A div, not a form: the image uploaders inside carry their own buttons and dialogs. */}
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
          <CheckboxField
            checked={draft.is_visible}
            onCheckedChange={(checked) => patch({ is_visible: checked === true })}
            label="Show my profile in this makerspace's member directory"
          />
          <CheckboxField
            checked={draft.show_attended_events}
            onCheckedChange={(checked) => patch({ show_attended_events: checked === true })}
            label="Also show the events I have attended on my profile"
          />
        </div>

        <ImageUploader
          endpoint={`/member/makerspaces/${makerspaceId}/profile/image`}
          currentUrl={draft.avatar_url}
          label="Avatar"
          onChanged={refreshImages}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="profile-headline" label="Headline">
            <Input value={draft.headline} onChange={(event) => patch({ headline: event.target.value })} />
          </Field>
          <Field id="profile-institution" label="Institution">
            <Input value={draft.institution} onChange={(event) => patch({ institution: event.target.value })} />
          </Field>
        </div>
        <Field id="profile-bio" label="Bio">
          <Textarea rows={4} value={draft.bio} onChange={(event) => patch({ bio: event.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="profile-interests" label="Interests" helperText="Comma separated">
            <Input value={interests} onChange={(event) => { setDirty(true); setInterests(event.target.value); }} />
          </Field>
          <Field id="profile-languages" label="Languages" helperText="Comma separated">
            <Input value={languages} onChange={(event) => { setDirty(true); setLanguages(event.target.value); }} />
          </Field>
        </div>
        <Field
          id="profile-github"
          label="GitHub username"
          helperText={draft.github_contributions !== null ? <><span className="font-mono">{draft.github_contributions}</span> contributions in the last year.</> : undefined}
        >
          <Input value={draft.github_username} onChange={(event) => patch({ github_username: event.target.value })} />
        </Field>

        <div className="flex flex-col gap-3 border-t border-line pt-5">
          <SectionHeading as="h3" title="Projects" description="Things you have made. Removing one takes effect when you save." />
          {projects.map((project, index) => (
            <ProjectEditor
              key={project.id ?? `new-${index}`}
              makerspaceId={makerspaceId}
              project={project}
              imageUrl={
                draft.projects.find((row) => row.id === project.id)?.image_url ?? null
              }
              onChange={(next) =>
                editProjects(projects.map((row, position) => (position === index ? next : row)))
              }
              onRemove={() =>
                editProjects(projects.filter((_, position) => position !== index))
              }
              onImageChanged={refreshImages}
            />
          ))}
          <Button
            className="self-start"
            startIcon={<Plus />}
            onClick={() =>
              editProjects([...projects, { title: "", description: "", links: [] }])
            }
          >
            Add a project
          </Button>
        </div>

        <ErrorText message={save.error ? (save.error instanceof Error ? save.error.message : "Could not save.") : null} />
        <Button variant="primary" className="self-start" loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save profile
        </Button>
      </div>
    </AccountCard>
  );
}
