import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { Loader } from "../../components/ui";
import { ChangePasswordGate } from "./ChangePasswordGate";
import { LoginPanel } from "./LoginPanel";
import { MakerspacePicker } from "./MakerspacePicker";
import { StaffAccessDenied } from "./StaffAccessDenied";
import { StaffWorkspace } from "./StaffWorkspace";
import { RecoveryQuarantinePanel } from "./RecoveryQuarantinePanel";
import { useStaffSession } from "./useStaffSession";

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
    routeMakerspace,
    routeMakerspaceSlug,
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

  const isSuperadmin = user.is_superuser || user.role === "superadmin";

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

  if (singleTenantLocked && makerspaces.isLoading) {
    return <StaffLoading message="Checking makerspace access…" />;
  }

  const hasSingleTenantAccess =
    !singleTenantLocked || Boolean(activeMakerspace);

  if (!hasSingleTenantAccess) {
    return (
      <StaffAccessDenied
        makerspaceName={tenant.bootstrap?.makerspace.name}
        onSignOut={signOut}
      />
    );
  }

  if (!singleTenantLocked && routeMakerspaceSlug && makerspaces.isLoading) {
    return <StaffLoading message="Opening makerspace…" />;
  }

  if (!singleTenantLocked && routeMakerspace && routeMakerspace.id !== selected) {
    return <StaffLoading message="Opening makerspace…" />;
  }

  if (!singleTenantLocked && selected !== null && makerspaces.isLoading) {
    return <StaffLoading message="Restoring makerspace…" />;
  }

  if (!singleTenantLocked && isSuperadmin && selected !== null && !activeMakerspace) {
    return (
      <MakerspacePicker
        makerspaces={makerspaces.data ?? []}
        loading={makerspaces.isLoading}
        username={user.username}
        onSelect={chooseMakerspace}
        onSignOut={signOut}
      />
    );
  }

  if (!singleTenantLocked && isSuperadmin && selected === null) {
    return (
      <MakerspacePicker
        makerspaces={makerspaces.data ?? []}
        loading={makerspaces.isLoading}
        username={user.username}
        onSelect={chooseMakerspace}
        onSignOut={signOut}
      />
    );
  }

  const activeMembership = user.makerspaces.find((item) => item.id === selected);
  const activeActions = activeMembership?.actions ?? [];
  const makerspaceList = makerspaces.data ?? [];

  return (
    <StaffWorkspace
      activeMakerspace={activeMakerspace}
      actions={activeActions}
      canConfigureMachineTypes={activeMembership?.can_configure_machine_types ?? isSuperadmin}
      isMachineOnly={activeMembership?.is_machine_only ?? false}
      guestOnly={guestOnly}
      isSuperadmin={isSuperadmin}
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
