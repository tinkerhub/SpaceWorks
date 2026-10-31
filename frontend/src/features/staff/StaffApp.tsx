import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { Link, Navigate, useLocation } from "react-router-dom";
import { Button, EmptyState, Loader } from "../../components/ui";
import { ChangePasswordGate } from "./ChangePasswordGate";
import { LoginPanel } from "./LoginPanel";
import { MakerspacePicker } from "./MakerspacePicker";
import { StaffAccessDenied } from "./StaffAccessDenied";
import { StaffWorkspace } from "./StaffWorkspace";
import { StaffPlatformPage } from "./StaffPlatformPage";
import { RecoveryQuarantinePanel } from "./RecoveryQuarantinePanel";
import { useStaffSession } from "./useStaffSession";
import { canManagePlatform, hasOperationalOverride, isGlobalStaffAdmin } from "./staffSelection";
import { tabFromStaffPath } from "./staffTabs";

// Route-level wait: the mark and a loader centred on the page, with the reason in words.
function StaffLoading({ message }: { message: string }) {
  return (
    <main className="grid min-h-dvh place-items-center bg-subtle px-4 text-ink">
      <div className="flex flex-col items-center gap-4 text-center">
        <SpaceWorksBadge />
        <Loader label={message} />
        <p aria-hidden="true" className="text-body-ui text-ink-muted">{message}</p>
      </div>
    </main>
  );
}

export function StaffApp({ guestOnly = false }: { guestOnly?: boolean }) {
  const location = useLocation();
  const {
    activeMakerspace,
    chooseMakerspace,
    login,
    makerspaces,
    queryClient,
    recovery,
    refreshAuthUser,
    restoring,
    identityReady,
    authorizationError,
    makerspacesLoading,
    retryMakerspaces,
    selection,
    sessionNotice,
    selected,
    setTab,
    setUser,
    signOut,
    singleTenantLocked,
    socialLoginSucceeded,
    tenant,
    user,
  } = useStaffSession(guestOnly);
  if (restoring) {
    return <StaffLoading message="Restoring session…" />;
  }

  if (!user) {
    return (
      <LoginPanel
        error={login.error?.message}
        notice={sessionNotice}
        guestOnly={guestOnly}
        isPending={login.isPending}
        onSubmit={login.mutate}
        onSocialSuccess={socialLoginSucceeded}
      />
    );
  }

  if (user.must_change_password) {
    return (
      <ChangePasswordGate
        username={user.username}
        onChanged={() => {
          // Clear the gate AND drop any error-cached protected queries so the
          // console opens with fresh data instead of a stale 403.
          queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
          setUser({ ...user, must_change_password: false });
          refreshAuthUser();
        }}
        onSignOut={signOut}
      />
    );
  }

  const isSuperadmin = isGlobalStaffAdmin(user);

  if (isSuperadmin && recovery.data?.mode === "quarantined") {
    return (
      <RecoveryQuarantinePanel
        state={recovery.data}
        onAcknowledged={(next) => {
          queryClient.setQueryData(["deployment-recovery-state"], next);
          queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
        }}
      />
    );
  }

  if (!identityReady) {
    if (!authorizationError) return <StaffLoading message="Checking account access…" />;
    return (
      <main className="grid min-h-dvh place-items-center bg-subtle px-4 text-ink">
        <EmptyState title="Could not verify account access" description="Retry to check your current permissions before opening staff pages."
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={refreshAuthUser}>Retry account access</Button>
            <Button variant="secondary" onClick={signOut}>Sign out</Button>
          </div>} />
      </main>
    );
  }

  const platformAvailable = canManagePlatform(user, singleTenantLocked);
  const originLocked = singleTenantLocked || user.staff_context?.scope_kind === "makerspace";
  if (!guestOnly && tabFromStaffPath(location.pathname, false) === "platform") {
    if (location.pathname !== "/admin/platform") return <Navigate replace to="/admin/platform" />;
    if (!platformAvailable) return (
      <main className="grid min-h-dvh place-items-center bg-subtle px-4 text-ink">
        <EmptyState title="Platform settings unavailable" description={originLocked
          ? "This site's staff session is pinned to its makerspace. Sign in through the operator-configured shared portal for platform settings."
          : "This session does not have verified platform management access. Sign in through a trusted platform portal with a permitted global account."}
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button asChild variant="primary"><Link to="/admin">Staff console</Link></Button>
            <Button variant="secondary" onClick={signOut}>Sign out</Button>
          </div>} />
      </main>
    );
    return <StaffPlatformPage user={user} onSignOut={signOut} makerspaces={makerspaces.data ?? []}
      loading={makerspacesLoading} error={makerspaces.isError}
      onRetry={retryMakerspaces} onSelect={chooseMakerspace} />;
  }

  const globalPicker = !guestOnly && !singleTenantLocked && isSuperadmin && location.pathname.replace(/\/+$/, "") === "/admin";
  if (selection.kind === "loading" && !(globalPicker && makerspacesLoading)) {
    return <StaffLoading message="Checking makerspace access…" />;
  }

  if (singleTenantLocked && selection.kind === "unavailable") {
    return (
      <StaffAccessDenied
        makerspaceName={tenant.bootstrap?.makerspace.name}
        onSignOut={signOut}
      />
    );
  }

  if (singleTenantLocked && selection.kind === "error") {
    return (
      <main className="grid min-h-dvh place-items-center bg-subtle px-4 text-ink">
        <EmptyState
          title="Could not check makerspace access"
          description="Retry to check whether this account can operate this site's makerspace."
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={retryMakerspaces}>Retry</Button>
            <Button variant="secondary" onClick={signOut}>Sign out</Button>
          </div>}
        />
      </main>
    );
  }

  if (selection.kind !== "selected") {
    return (
      <MakerspacePicker
        makerspaces={makerspaces.data ?? []}
        loading={makerspacesLoading}
        error={selection.kind === "error"}
        unavailable={selection.kind === "unavailable"}
        globalAdmin={isSuperadmin}
        platformAvailable={!guestOnly && platformAvailable}
        originLocked={originLocked}
        onRetry={retryMakerspaces}
        username={user.username}
        onSelect={chooseMakerspace}
        onSignOut={signOut}
      />
    );
  }

  const activeMembership = user.makerspaces.find((item) => item.id === selected);
  const activeActions = activeMembership?.actions ?? [];
  const makerspaceList = makerspaces.data ?? [];
  const operationalSuperadmin = hasOperationalOverride(user, activeMakerspace);

  return (
    <StaffWorkspace
      activeMakerspace={activeMakerspace}
      actions={activeActions}
      canConfigureMachineTypes={activeMembership?.can_configure_machine_types ?? operationalSuperadmin}
      isMachineOnly={activeMembership?.is_machine_only ?? false}
      guestOnly={guestOnly}
      isSuperadmin={operationalSuperadmin}
      makerspaces={makerspaceList}
      onAuthRefresh={refreshAuthUser}
      selected={selected}
      setSelected={chooseMakerspace}
      setTab={setTab}
      signOut={signOut}
      singleTenantLocked={singleTenantLocked}
      user={user}
    />
  );
}
