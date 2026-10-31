import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import {
  addAuthExpiredListener, clearAccessToken, fetchMe, getSessionGeneration,
  logout as logoutStaff, refreshAccessToken, setAccessToken, staffRequest,
  type PasswordLoginRequest, type PasswordLoginResponse, type StaffAuthUser,
} from "../../lib/api";
import { getSessionRevision, LogoutIncompleteError, subscribeSession } from "../../lib/apiSession";
import type { SocialLoginResult } from "../auth/socialSdk";
import type { RecoveryState } from "./RecoveryQuarantinePanel";
import { persistSelectedMakerspace, persistStaffTab, readStoredMakerspace, staffBasePath } from "./staffTabs";
import { useTenant } from "../../lib/tenant";
import { wipeOfflineScopes } from "./eventCheckInOfflineStore";
import { staffMeKey } from "./paymentsApi";
import { useStaffMakerspaces } from "./useStaffMakerspaces";
import { isGlobalStaffAdmin, resolveStaffSelection, staffChoicePath, type StaffSelection } from "./staffSelection";

type SelectionIntent = {
  sequence: number;
  generation: number;
  sourceKey: string;
  targetPath: string;
  id: number | null;
};

export function useStaffSession(guestOnly: boolean) {
  useSyncExternalStore(subscribeSession, getSessionRevision, getSessionRevision);
  const tenant = useTenant();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState<StaffAuthUser | null>(null);
  const [hint, setHint] = useState(readStoredMakerspace);
  const [restoring, setRestoring] = useState(true);
  const [refreshingAuth, setRefreshingAuth] = useState(false);
  const [refreshingMakerspaces, setRefreshingMakerspaces] = useState(false);
  const [authorizationError, setAuthorizationError] = useState(false);
  const [identityGeneration, setIdentityGeneration] = useState<number | null>(null);
  const [sessionNotice, setSessionNotice] = useState("");
  const [intent, setIntent] = useState<SelectionIntent | null>(null);
  const mounted = useRef(false);
  const authLifetime = useRef(0);
  const choiceSequence = useRef(0);
  const generation = getSessionGeneration();
  const renderedChoice = choiceSequence.current;
  const singleTenantLocked = tenant.mode === "single";
  const current = useCallback((lifetime: number, authGeneration: number) =>
    mounted.current && authLifetime.current === lifetime && getSessionGeneration() === authGeneration, []);
  const hydrateUser = useCallback((next: StaffAuthUser) => {
    setUser(next);
    setIdentityGeneration(getSessionGeneration());
    queryClient.setQueryData(staffMeKey, next);
  }, [queryClient]);
  const clearLocalSession = useCallback(() => {
    authLifetime.current += 1;
    choiceSequence.current += 1;
    setUser(null);
    setHint(null);
    setIntent(null);
    setRefreshingAuth(false);
    setRefreshingMakerspaces(false);
    setIdentityGeneration(null);
    setAuthorizationError(false);
    setRestoring(false);
    persistSelectedMakerspace(null);
    persistStaffTab("");
    queryClient.clear();
  }, [queryClient]);
  const expireSession = useCallback(() => {
    clearLocalSession();
    void wipeOfflineScopes("staff:").catch(() => {});
  }, [clearLocalSession]);
  useEffect(() => addAuthExpiredListener(expireSession), [expireSession]);

  useEffect(() => {
    mounted.current = true;
    const lifetime = ++authLifetime.current;
    const authGeneration = getSessionGeneration();
    void (async () => {
      try {
        const refreshed = await refreshAccessToken();
        if (!current(lifetime, authGeneration)) return;
        if (refreshed) {
          const next = await fetchMe();
          if (current(lifetime, authGeneration)) hydrateUser(next);
        }
      } catch {
        if (current(lifetime, authGeneration)) {
          clearAccessToken();
          setUser(null);
          setRestoring(false);
        }
      } finally {
        if (current(lifetime, authGeneration)) setRestoring(false);
      }
    })();
    return () => { mounted.current = false; authLifetime.current += 1; };
  }, [current, hydrateUser]);

  const makerspaces = useStaffMakerspaces(Boolean(user) && !user?.must_change_password);
  // Keep mounted forms during ordinary background refetches. Explicit identity/access
  // refreshes still fence panels until their refreshed allowed list settles.
  const makerspacesLoading = refreshingMakerspaces || makerspaces.isPending;
  const identityReady = Boolean(user) && !restoring && !refreshingAuth && !authorizationError &&
    identityGeneration === generation;
  // Fence old authority first; publish the verified identity independently of list success.
  const refreshAuthUser = useCallback(() => {
    if (!mounted.current || generation !== getSessionGeneration()) return;
    const lifetime = ++authLifetime.current;
    const authGeneration = getSessionGeneration();
    setRefreshingAuth(true);
    setRefreshingMakerspaces(true);
    setAuthorizationError(false);
    setIntent(null);
    void (async () => {
      try {
        await queryClient.cancelQueries({ queryKey: ["staff", "makerspaces"] });
        if (!current(lifetime, authGeneration)) return;
        const next = await fetchMe();
        if (!current(lifetime, authGeneration)) return;
        hydrateUser(next);
        setRefreshingAuth(false);
        try {
          await queryClient.resetQueries({ queryKey: ["staff", "makerspaces"] }, { throwOnError: true });
        } catch { /* The allowed-list query owns its error; the identity remains verified. */ }
      } catch {
        if (current(lifetime, authGeneration)) setAuthorizationError(true);
      } finally {
        if (current(lifetime, authGeneration)) {
          setRefreshingAuth(false);
          setRefreshingMakerspaces(false);
        }
      }
    })();
  }, [current, generation, hydrateUser, queryClient]);
  // Password rotation installs a new session generation. Verify it before reopening
  // panels; stale completions still cannot publish across the lifetime/generation guard.
  useEffect(() => {
    if (user && identityGeneration !== null && identityGeneration !== generation) refreshAuthUser();
  }, [generation, identityGeneration, refreshAuthUser, user]);

  const beginChoice = useCallback((id: number | null, targetPath: string) => {
    const sequence = ++choiceSequence.current;
    setIntent({ sequence, generation: getSessionGeneration(), sourceKey: location.key, targetPath, id });
    setHint(id);
    if (id === null) {
      // This intent wins before the old scoped frame can canonicalize its workspace.
      persistSelectedMakerspace(null);
    }
    navigate(targetPath, { state: { staffPicker: id === null, staffMakerspaceId: id } });
  }, [location.key, navigate]);
  const completeLogin = useCallback((access: string, next: StaffAuthUser) => {
    // Installation can fail atomically; retain the caller's ownership to report it.
    setAccessToken(access);
    authLifetime.current += 1;
    choiceSequence.current += 1;
    setSessionNotice("");
    setAuthorizationError(false);
    setRefreshingAuth(false);
    setRefreshingMakerspaces(false);
    setRestoring(false);
    setIntent(null);
    hydrateUser(next);
    if (!singleTenantLocked && isGlobalStaffAdmin(next)) beginChoice(null, staffBasePath(guestOnly));
  }, [beginChoice, guestOnly, hydrateUser, singleTenantLocked]);
  const loginMutation = useMutation({
    mutationFn: ({ payload }: { payload: { username: string; password: string }; lifetime: number; authGeneration: number }) =>
      staffRequest<PasswordLoginResponse<StaffAuthUser>>("/auth/login", {
        method: "POST", credentials: "include",
        body: JSON.stringify({ ...payload, surface: "staff" } satisfies PasswordLoginRequest),
      }),
    onSuccess: (data, { lifetime, authGeneration }) => {
      if (current(lifetime, authGeneration)) completeLogin(data.access, data.user);
    },
  });
  const login = { ...loginMutation, mutate: (payload: { username: string; password: string }) => {
    if (!mounted.current) return;
    // Invalidate older notices/completions at the public call, before mutationFn runs.
    const lifetime = ++authLifetime.current;
    setSessionNotice("");
    loginMutation.mutate({ payload, lifetime, authGeneration: getSessionGeneration() });
  } };
  const socialLifetime = authLifetime.current;
  const socialLoginSucceeded = useCallback((result: SocialLoginResult) => {
    if (!current(socialLifetime, generation)) return;
    setSessionNotice("");
    try {
      completeLogin(result.access, result.user as unknown as StaffAuthUser);
    } catch (error) {
      if (current(socialLifetime, generation)) {
        setSessionNotice(error instanceof Error ? error.message : "Unable to sign in. Try again.");
      }
    }
  }, [completeLogin, current, generation, socialLifetime]);

  const recovery = useQuery({
    queryKey: ["deployment-recovery-state"],
    queryFn: () => staffRequest<RecoveryState>("/recovery"),
    enabled: Boolean(identityReady && user && isGlobalStaffAdmin(user)), retry: false,
  });
  const pending = intent && intent.sequence === renderedChoice && intent.generation === generation &&
    intent.sourceKey === location.key && intent.targetPath !== location.pathname &&
    !makerspaces.isError && !authorizationError &&
    (intent.id === null || makerspaces.data?.some((space) => space.id === intent.id));
  useEffect(() => {
    if (intent && !pending) setIntent(null); // Acknowledged, superseded navigation, or withdrawn target.
  }, [intent, pending]);
  const routeState = location.state as { staffPicker?: boolean; staffMakerspaceId?: number } | null;
  let selection: StaffSelection = resolveStaffSelection({
    spaces: makerspaces.data ?? [], loading: !identityReady || makerspacesLoading,
    error: authorizationError || makerspaces.isError, pathname: location.pathname, guestOnly,
    lockedId: singleTenantLocked ? tenant.makerspaceId : null,
    globalAdmin: Boolean(user && isGlobalStaffAdmin(user)),
    hint: typeof routeState?.staffMakerspaceId === "number" ? routeState.staffMakerspaceId : hint,
    explicitId: typeof routeState?.staffMakerspaceId === "number" ? routeState.staffMakerspaceId : null,
    picker: routeState?.staffPicker === true,
  });
  if (pending) selection = { kind: "loading" };
  if (singleTenantLocked && tenant.makerspaceId === null) {
    selection = { kind: tenant.error ? "error" : "loading" };
  }
  const activeMakerspace = selection.kind === "selected" ? selection.makerspace : undefined;
  const selected = activeMakerspace?.id ?? null;
  useEffect(() => {
    if (!user || generation !== getSessionGeneration() || renderedChoice !== choiceSequence.current) return;
    if (selected !== null) {
      persistSelectedMakerspace(selected);
      setHint(selected);
    }
  }, [generation, renderedChoice, selected, user]);
  const chooseMakerspace = useCallback((id: number | null) => {
    if (!mounted.current || singleTenantLocked || !user || generation !== getSessionGeneration() ||
      renderedChoice !== choiceSequence.current || pending) return;
    if (id === null) { beginChoice(null, staffBasePath(guestOnly)); return; }
    if (makerspaces.isError || !identityReady || makerspacesLoading || authorizationError) return;
    const space = makerspaces.data?.find((item) => item.id === id);
    if (space) beginChoice(id, staffChoicePath(space, user, guestOnly, location.pathname));
  }, [authorizationError, beginChoice, generation, guestOnly, identityReady, location.pathname, makerspaces.data, makerspaces.isError, makerspacesLoading, pending, renderedChoice, singleTenantLocked, user]);

  const signOut = async () => {
    const logout = logoutStaff(); // Synchronously clears token and bumps generation before its first await.
    if (mounted.current) clearLocalSession();
    const lifetime = authLifetime.current;
    const signedOutGeneration = getSessionGeneration();
    // No late local cleanup: a new login may have started during either operation.
    const [logoutResult] = await Promise.allSettled([logout, wipeOfflineScopes("staff:")]);
    if (logoutResult.status === "rejected" && current(lifetime, signedOutGeneration)) {
      setSessionNotice(logoutResult.reason instanceof LogoutIncompleteError
        ? logoutResult.reason.message : new LogoutIncompleteError().message);
    }
  };
  return {
    activeMakerspace, chooseMakerspace, login, makerspaces, queryClient, recovery,
    refreshAuthUser, restoring, selected, selection, setTab: persistStaffTab, setUser,
    identityReady, authorizationError, makerspacesLoading,
    sessionNotice, signOut, singleTenantLocked, socialLoginSucceeded, tenant, user,
    retryMakerspaces: () => { if (authorizationError) refreshAuthUser(); else void makerspaces.refetch(); },
  };
}
