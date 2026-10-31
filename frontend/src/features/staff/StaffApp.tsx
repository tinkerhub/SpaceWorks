import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { Button, EmptyState, Loader } from "../../components/ui";
import { ChangePasswordGate } from "./ChangePasswordGate";
import { LoginPanel } from "./LoginPanel";
import { MakerspacePicker } from "./MakerspacePicker";
import { StaffAccessDenied } from "./StaffAccessDenied";
import { StaffWorkspace } from "./StaffWorkspace";
import { RecoveryQuarantinePanel } from "./RecoveryQuarantinePanel";
import { useStaffSession } from "./useStaffSession";
import { hasOperationalOverride, isGlobalStaffAdmin } from "./staffSelection";

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
  const {
    activeMakerspace,
    chooseMakerspace,
    login,
    makerspaces,
    queryClient,
    recovery,
    refreshAuthUser,
    restoring,
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

  if (selection.kind === "loading") {
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
        loading={false}
        error={selection.kind === "error"}
        unavailable={selection.kind === "unavailable"}
        globalAdmin={isSuperadmin}
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
