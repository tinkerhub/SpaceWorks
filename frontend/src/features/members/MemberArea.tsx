import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import type { ArchivedPaymentSummary, MembershipOutcome, MembershipPolicyEnum } from "../../generated/api";
import { bootstrapTenant, memberRequest, refreshAccessToken, StructuredApiError } from "../../lib/api";
import { MakerspaceSiteHeader, PlatformSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Callout, ErrorText, Loader, Spinner, useToast } from "../../components/ui";
import { moduleEnabled } from "../../lib/modules";
import { AccountCard } from "../account/AccountCard";
import { MemberAuthPanel } from "./MemberAuthPanel";
import { MemberPasswordRequired } from "./MemberAccountSection";
import { JoinMembershipCta } from "./JoinMembershipCta";
import { presenceStartLocation } from "./geolocation";
import type { MemberActivity } from "./MemberActivity";
import { ArchivedPaymentsNotice, MemberHeaderCard, type Membership, type Presence, type Waiver } from "./MemberAreaSections";
import { MemberAreaTabs } from "./MemberAreaTabs";
import type { ClaimableInvitation } from "./MemberReferrals";
import type { MemberPayment } from "./MemberPayments";

type Memberships = { memberships: Membership[]; requests: { makerspace: { slug: string; name: string }; state: string; kind: string }[] };
type Invitations = { invitations: ClaimableInvitation[] };
type Profile = { username: string; email_verified: boolean; must_change_password: boolean };
type ReferralOutcome = { state: "invited" };
type ClaimOutcome = { id: number; outcome: "active" | "pending_approval" };
function message(error: unknown) {
  if (error instanceof StructuredApiError && error.status === 401) return "Sign in to manage your membership.";
  return error instanceof Error ? error.message : "Unable to complete that action.";
}

export function MemberArea() {
  const { slug = "" } = useParams();
  const client = useQueryClient();
  const { showToast } = useToast();
  const [restoring, setRestoring] = useState(true);
  const [showSignIn, setShowSignIn] = useState(false);
  useEffect(() => {
    refreshAccessToken().then(() => client.invalidateQueries({ queryKey: ["member"] })).finally(() => setRestoring(false));
  }, [client]);
  const bootstrap = useQuery({ queryKey: ["member", slug, "bootstrap"], queryFn: () => bootstrapTenant({ slug: slug || undefined }), retry: false });
  const resolvedSlug = slug || bootstrap.data?.makerspace.slug || "";
  const makerspaceId = bootstrap.data?.makerspace.id ?? -1;
  // Only the module-specific sections are gated. Payments (receipts, history, archived
  // payments), the membership card, waiver, presence and staff-invitation claims stay:
  // they are deliberate survivors of their modules being switched off.
  const membershipOn = moduleEnabled(bootstrap.data?.modules, "membership");
  const eventsOn = moduleEnabled(bootstrap.data?.modules, "events");
  const memberships = useQuery({ queryKey: ["member", "memberships"], queryFn: () => memberRequest<Memberships>("/memberships/me"), retry: false });
  const unauthenticated = memberships.error instanceof StructuredApiError && memberships.error.status === 401;
  const membership = memberships.data?.memberships.find((row) => row.makerspace.slug === resolvedSlug);
  const active = membership?.membership_status === "active";
  const requested = memberships.data?.requests.some((row) => row.makerspace.slug === resolvedSlug && row.state === "requested");
  const profile = useQuery({ queryKey: ["member", "profile"], queryFn: () => memberRequest<Profile>("/auth/me"), enabled: Boolean(memberships.data), retry: false });
  const invitations = useQuery({ queryKey: ["member", "invitations"], queryFn: () => memberRequest<Invitations>("/memberships/invitations"), enabled: Boolean(memberships.data), retry: false });
  const waiver = useQuery({ queryKey: ["member", resolvedSlug, "waiver"], queryFn: () => memberRequest<Waiver>(`/member/makerspaces/${makerspaceId}/waiver`), enabled: makerspaceId >= 0 && active, retry: false });
  const presence = useQuery({ queryKey: ["member", resolvedSlug, "presence"], queryFn: () => memberRequest<Presence>(`/public/${resolvedSlug}/presence-sessions/current`), enabled: Boolean(resolvedSlug) && active, retry: false });
  const activity = useQuery({ queryKey: ["member", resolvedSlug, "activity"], queryFn: () => memberRequest<MemberActivity>(`/member/makerspaces/${makerspaceId}/activity`), enabled: membershipOn && makerspaceId >= 0 && active, retry: false });
  const payments = useQuery({ queryKey: ["member", resolvedSlug, "payments"], queryFn: () => memberRequest<MemberPayment[]>(`/member/makerspaces/${makerspaceId}/payments`), enabled: makerspaceId >= 0 && active, retry: false });
  // Deliberately NOT gated on `memberships.data`. A member whose only makerspace is archived
  // gets an empty `/memberships/me`, and a signed-out one gets a 401 -- gating on it meant the
  // people this recovery route exists for were exactly the people who never saw the link.
  const archivedPayments = useQuery({ queryKey: ["member", "archived-payments"], queryFn: () => memberRequest<ArchivedPaymentSummary[]>("/member/archived-payments"), retry: false });
  // A 404 means the payments app is TOMBSTONED on this deployment, so the recovery route is
  // genuinely gone -- advertising it would hand the member a link straight to a not-found
  // page. Every other error (401 signed-out, network) still warrants the fallback.
  const archivedRemoved = archivedPayments.error instanceof StructuredApiError && archivedPayments.error.status === 404;
  const archivedUnknown = !archivedRemoved && (archivedPayments.isError || (bootstrap.isError && !archivedPayments.data?.length));
  const refresh = () => client.invalidateQueries({ queryKey: ["member"] });
  // Every mutation confirms in a toast; failures also stay visible inline below.
  const done = (text: string) => () => { showToast(text, { tone: "success" }); return refresh(); };
  const failed = (text: string) => () => showToast(text, { tone: "error" });
  const request = useMutation({ mutationFn: () => memberRequest<MembershipOutcome>(`/public/${resolvedSlug}/membership-requests`, { method: "POST", body: JSON.stringify({}) }), onSuccess: done("Membership request sent"), onError: failed("Could not send the request") });
  const accept = useMutation({ mutationFn: () => memberRequest(`/member/makerspaces/${makerspaceId}/waiver/accept`, { method: "POST" }), onSuccess: done("Waiver accepted"), onError: failed("Could not accept the waiver") });
  const start = useMutation({ mutationFn: async () => {
    const location = await presenceStartLocation(Boolean(bootstrap.data?.makerspace.geofence_enabled));
    return memberRequest(`/public/${resolvedSlug}/presence-sessions`, {
      method: "POST",
      body: JSON.stringify({ duration_minutes: 120, ...(location ?? {}) }),
    });
  }, onSuccess: done("Presence started"), onError: failed("Could not start presence") });
  const end = useMutation({ mutationFn: () => memberRequest(`/public/${resolvedSlug}/presence-sessions/current/end`, { method: "POST" }), onSuccess: done("Presence ended"), onError: failed("Could not end presence") });
  const refer = useMutation({ mutationFn: (inviteEmail: string) => memberRequest<ReferralOutcome>(`/member/makerspaces/${makerspaceId}/referrals`, { method: "POST", body: JSON.stringify({ invite_email: inviteEmail }) }), onSuccess: done("Referral sent"), onError: failed("Referral not sent") });
  const claim = useMutation({ mutationFn: (id: number) => memberRequest<ClaimOutcome>(`/memberships/invitations/${id}/claim`, { method: "POST" }), onSuccess: done("Invitation claimed"), onError: failed("Could not claim the invitation") });
  const generatePaymentLink = useMutation({ mutationFn: (id: number) => memberRequest<{ checkout_url: string }>(`/member/makerspaces/${makerspaceId}/payments/${id}/checkout`, { method: "POST" }), onSuccess: (data) => { refresh(); window.location.assign(data.checkout_url); }, onError: failed("Could not create a payment link") });
  const spaceInvitations = invitations.data?.invitations.filter((item) => item.makerspace.slug === resolvedSlug) ?? [];
  const error = bootstrap.error ?? (!unauthenticated ? memberships.error : null) ?? request.error ?? accept.error ?? start.error ?? end.error ?? activity.error ?? generatePaymentLink.error;
  const policy: MembershipPolicyEnum | undefined = bootstrap.data?.makerspace.membership_policy;
  // The join POST is refused while the membership module is off, so the call to action goes too.
  const offerJoin = membershipOn && Boolean(policy) && !membership && !requested;

  if (restoring) return <main className="grid min-h-dvh place-items-center bg-subtle"><Loader label="Restoring session" /></main>;
  if (showSignIn) return <MemberAuthPanel makerspaceSlug={resolvedSlug} onCancel={() => setShowSignIn(false)} onAuthenticated={() => { setShowSignIn(false); void client.invalidateQueries({ queryKey: ["member"] }); }} />;
  if (profile.data?.must_change_password) return <MemberPasswordRequired username={profile.data.username} onChanged={refresh} />;

  const space = bootstrap.data;
  const spaceName = space ? space.branding?.display_name || space.makerspace.name : undefined;
  // Without a resolved makerspace (`/member` on the central portal) there is no space to brand.
  const siteHeader = space
    ? <MakerspaceSiteHeader homePath={slug ? `/m/${slug}` : "/"} name={spaceName ?? space.makerspace.name} logoUrl={space.makerspace.logo_url} moduleEnabled={(key) => moduleEnabled(space.modules, key)} statsEnabled={space.makerspace.public_stats_enabled} page="Member area" />
    : <PlatformSiteHeader page="Member area" />;
  // reset, not invalidate: a refetch that 401s keeps the old data, which would still look signed in.
  const signedOut = () => { void client.resetQueries({ queryKey: ["member"] }); };
  const signInButton = <Button variant="secondary" onClick={() => setShowSignIn(true)}>Sign in</Button>;

  const standing = <>
    {bootstrap.isLoading ? <AccountCard title="Joining options" description={<span className="inline-flex items-center gap-2"><Spinner decorative className="size-4" />Loading makerspace joining options…</span>} /> : null}
    {bootstrap.isError ? <Callout tone="danger" role="alert">{message(bootstrap.error)}</Callout> : null}
    {offerJoin && memberships.isLoading ? <AccountCard title="Join this makerspace" description={<span className="inline-flex items-center gap-2"><Spinner decorative className="size-4" />Checking your sign-in status…</span>} /> : null}
    {offerJoin && policy && !memberships.isLoading ? <JoinMembershipCta policy={policy} signedIn={Boolean(memberships.data)} pending={request.isPending} onJoin={() => request.mutate()} onSignIn={() => setShowSignIn(true)} /> : null}
    {requested ? <AccountCard title="Membership request sent" description="Staff will review your request." /> : null}
    {unauthenticated && policy?.startsWith("invite") ? <p className="text-body-ui text-ink-muted">Sign in to view memberships or claim an invitation.</p> : null}
  </>;

  return (
    <PublicShell header={siteHeader}>
      <PublicContainer width="md" className="flex flex-col gap-6">
        <MemberHeaderCard
          spaceName={spaceName}
          username={profile.data?.username}
          membership={membership}
          emailVerified={profile.data?.email_verified}
          action={memberships.isError ? signInButton : null}
        />
        {archivedPayments.data?.length ? <ArchivedPaymentsNotice known /> : null}
        {archivedUnknown ? <ArchivedPaymentsNotice known={false} /> : null}
        {error && !bootstrap.isError ? <ErrorText message={message(error)} /> : null}
        {memberships.data ? (
          <MemberAreaTabs
            standing={standing}
            username={profile.data?.username}
            membership={membership}
            membershipOn={membershipOn}
            eventsOn={eventsOn}
            makerspaceId={makerspaceId}
            makerspaceSlug={resolvedSlug}
            waiver={waiver.data}
            presence={presence.data}
            activity={activity.data}
            payments={payments.data}
            accepting={accept.isPending}
            presenceBusy={start.isPending || end.isPending}
            canStartPresence={Boolean(bootstrap.data)}
            checkoutPaymentId={generatePaymentLink.isPending ? generatePaymentLink.variables : undefined}
            onAccept={() => accept.mutate()}
            onTogglePresence={() => (presence.data?.active ? end.mutate() : start.mutate())}
            onCheckout={(paymentId) => generatePaymentLink.mutate(paymentId)}
            onSignedOut={signedOut}
            referrals={Boolean(resolvedSlug) && makerspaceId >= 0 ? {
              canRefer: active && Boolean(membership?.can_refer),
              referralsEnabled: membershipOn && active && Boolean(membership?.referrals_enabled),
              emailVerified: profile.data?.email_verified,
              invitations: spaceInvitations,
              invitationsLoading: invitations.isLoading,
              invitationError: invitations.error instanceof Error ? invitations.error : null,
              onRefer: (email) => refer.mutateAsync(email),
              onClaim: (id) => claim.mutate(id),
              isReferring: refer.isPending,
              claimingId: claim.isPending ? claim.variables : null,
              referralError: refer.error instanceof Error ? refer.error : null,
              referralSuccess: refer.data ? "Referral invitation sent." : null,
              claimError: claim.error instanceof Error ? claim.error : null,
              claimSuccess: claim.data ? claim.data.outcome === "active" ? "You are now an active member." : "Your invitation is waiting for manager approval." : null,
            } : null}
          />
        ) : <div className="flex flex-col gap-5">{standing}</div>}
      </PublicContainer>
    </PublicShell>
  );
}
