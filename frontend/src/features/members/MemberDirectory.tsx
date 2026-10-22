import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { Avatar, Chip, EmptyState, Spinner, type AvatarTone } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { cn } from "../../lib/cn";
import { AccountCard } from "../account/AccountCard";
import type { MemberProfile } from "./MemberProfilePanel";

type DirectoryEntry = {
  membership_id: number;
  display_name: string;
  headline: string;
  avatar_url: string | null;
};

type Directory = { members: DirectoryEntry[]; hidden_count: number };

const IDENTITY_TONES: AvatarTone[] = ["accent", "secondary", "success", "warning"];

// Distributed by a stable id, never by render order, so a member keeps their colour.
function identityTone(identity: number): AvatarTone {
  return IDENTITY_TONES[identity % IDENTITY_TONES.length];
}

/**
 * Who else is here — but only the people who chose to be listed.
 *
 * The row carries a display name and an avatar and nothing else: the backend does not
 * send contact details on this endpoint at all, because otherwise "see who else is here"
 * is an address harvest available to anyone the space admits.
 */
export function MemberDirectory({ makerspaceId }: { makerspaceId: number }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const directory = useQuery({
    queryKey: ["member", "directory", makerspaceId],
    queryFn: () => staffRequest<Directory>(`/member/makerspaces/${makerspaceId}/directory`),
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["member", "directory", makerspaceId, openId],
    queryFn: () =>
      staffRequest<MemberProfile>(
        `/member/makerspaces/${makerspaceId}/directory/${openId}`,
      ),
    enabled: openId !== null,
    retry: false,
  });

  if (directory.isLoading) {
    return (
      <AccountCard title="Members" description={<span className="inline-flex items-center gap-2"><Spinner decorative className="size-4" />Loading members…</span>} />
    );
  }
  if (directory.isError) return null;

  const entries = directory.data?.members ?? [];
  const hidden = directory.data?.hidden_count ?? 0;

  return (
    <AccountCard
      title="Members"
      description={hidden > 0 ? `${hidden} more ${hidden === 1 ? "member has" : "members have"} not published a profile.` : "People in this makerspace who published a profile."}
    >
      {entries.length === 0 ? (
        <EmptyState title="Nobody has published a profile yet." description="Publish yours from your maker profile to be the first." />
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {entries.map((entry) => {
            const open = openId === entry.membership_id;
            return <li key={entry.membership_id}>
              <button
                className="flex w-full min-w-0 items-center gap-3 px-4 py-3 text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus"
                type="button"
                onClick={() => setOpenId(open ? null : entry.membership_id)}
                aria-expanded={open}
              >
                {/* Decorative: the name beside it already labels the row. */}
                <span aria-hidden="true" className="inline-flex"><Avatar src={entry.avatar_url} tone={identityTone(entry.membership_id)} name={entry.display_name} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink">{entry.display_name}</span>
                  {entry.headline ? (
                    <span className="block truncate text-body-ui text-ink-muted">{entry.headline}</span>
                  ) : null}
                </span>
                <ChevronDown aria-hidden="true" className={cn("size-5 shrink-0 text-ink-muted transition-transform duration-180 ease-standard", open && "rotate-180")} />
              </button>
              {/* Unmounted rather than hidden when collapsed, so keyboard users cannot
                  tab into links they cannot see. */}
              {open && detail.data ? (
                <ProfileDetail profile={detail.data} />
              ) : null}
            </li>;
          })}
        </ul>
      )}
    </AccountCard>
  );
}

function ProfileDetail({ profile }: { profile: MemberProfile }) {
  return (
    <div className="flex flex-col gap-3 border-t border-line bg-subtle px-4 py-4">
      {profile.institution ? (
        <p className="text-body-ui text-ink-muted">{profile.institution}</p>
      ) : null}
      {profile.bio ? <p className="text-body-ui text-ink">{profile.bio}</p> : null}
      <TagRow label="Interests" values={profile.interests} />
      <TagRow label="Languages" values={profile.languages} />
      {profile.education.length ? (
        <ul className="flex flex-col gap-1 text-body-ui text-ink-secondary">
          {profile.education.map((row, index) => (
            <li key={index}>{[row.qualification, row.institution, row.year].filter(Boolean).join(" · ")}</li>
          ))}
        </ul>
      ) : null}
      {profile.github_contributions !== null ? (
        <p className="text-body-ui text-ink-muted">
          <span className="font-mono">{profile.github_contributions}</span> GitHub contributions in the last year.
        </p>
      ) : null}
      {typeof profile.activity?.events_attended === "number" ? (
        <p className="text-body-ui text-ink-muted">
          <span className="font-mono">{profile.activity.events_attended}</span> events attended here.
        </p>
      ) : null}
      {profile.activity?.recent_attended_events?.length ? (
        <div>
          {/* "Recent" is load-bearing, not decoration: the backend caps this list, so a
              heading reading "Events attended" would claim to be the full history. The
              count above is the truthful total. */}
          <h3 className="text-label text-ink">Recently attended</h3>
          <ul className="mt-1 flex flex-col gap-1 text-body-ui text-ink-muted">
            {profile.activity.recent_attended_events.map((event) => (
              <li key={event.id}>
                {event.title} ·{" "}
                <span className="font-mono">{new Date(event.starts_at).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {profile.projects.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {profile.projects.map((project) => (
            <article key={project.id} className="min-w-0 rounded-lg border border-line bg-canvas p-3">
              {project.image_url ? (
                <img
                  src={project.image_url}
                  alt=""
                  className="mb-2 max-h-40 w-full rounded-md object-cover"
                />
              ) : null}
              <h3 className="text-label text-ink">{project.title}</h3>
              {project.description ? (
                <p className="mt-1 text-body-ui text-ink-muted">{project.description}</p>
              ) : null}
              {project.links.length ? (
                <ul className="mt-2 flex flex-wrap gap-3 text-body-ui">
                  {project.links.map((link, index) => (
                    <li key={index}>
                      {/* External and member-authored: noopener/noreferrer keeps the
                          destination from reaching back through window.opener. */}
                      <a
                        className="text-accent-ink underline underline-offset-4 hover:text-ink"
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TagRow({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-label text-ink">{label}</span>
      {values.map((value) => <Chip key={value} size="sm">{value}</Chip>)}
    </div>
  );
}
