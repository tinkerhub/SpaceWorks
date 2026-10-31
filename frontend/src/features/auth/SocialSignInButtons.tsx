import { useEffect, useMemo, useRef, useState } from "react";

import { Button, ErrorText } from "../../components/ui";
import { publicV1Request } from "../../lib/api";
import { useAuthActionOwner } from "./useAuthActionOwner";
import {
  beginOidcBrowser, completeOidcBrowserCallback, mountGoogleButton, signInWithApple,
  type SocialConfig, type SocialLoginResult, type SocialSurface,
} from "./socialSdk";

export function SocialSignInButtons({
  surface, onSuccess, email = "", makerspaceSlug = "", disabled = false, ownershipScope, isHostCurrent,
}: {
  surface: SocialSurface;
  onSuccess: (result: SocialLoginResult) => void;
  email?: string;
  makerspaceSlug?: string;
  disabled?: boolean;
  ownershipScope?: object;
  isHostCurrent?: () => boolean;
}) {
  const scope = useMemo(() => ({}), [surface, makerspaceSlug, email, disabled, ownershipScope]);
  const owner = useAuthActionOwner(scope);
  // Typed email does not define Google's provider identity; avoid a nonce request per keystroke.
  const googleScope = useMemo(() => ({}), [surface, makerspaceSlug, disabled, ownershipScope]);
  const googleOwner = useAuthActionOwner(googleScope);
  const discoveryOwner = useAuthActionOwner("social-discovery");
  const googleHost = useRef<HTMLDivElement>(null);
  const [discovery, setDiscovery] = useState<{ context: typeof discoveryOwner.context; config: SocialConfig; accounts: boolean }>();
  const config = discovery?.context === discoveryOwner.context ? discovery.config : undefined;
  const memberAccounts = discovery?.context === discoveryOwner.context ? discovery.accounts : true;
  const [status, setStatus] = useState({ context: owner.context, error: "", pending: "" });
  const [googleError, setGoogleError] = useState({ context: googleOwner.context, error: "" });
  const { error, pending } = status.context === owner.context ? status : { error: "", pending: "" };
  const hostCurrent = () => !disabled && (!isHostCurrent || isHostCurrent());

  useEffect(() => {
    let active = true;
    publicV1Request<{ social_auth?: SocialConfig; member_accounts?: { enabled: boolean } }>("/config")
      .then((result) => {
        if (active && discoveryOwner.isContextCurrent()) setDiscovery({ context: discoveryOwner.context,
          config: result.social_auth ?? {}, accounts: result.member_accounts?.enabled !== false });
      }).catch(() => {
        if (active && discoveryOwner.isContextCurrent()) setDiscovery({ context: discoveryOwner.context, config: {}, accounts: true });
      });
    return () => { active = false; };
  }, [discoveryOwner.context]);

  useEffect(() => {
    if (surface !== "member" || !hostCurrent()) return;
    const action = owner.capture();
    let active = true;
    const current = () => active && hostCurrent() && owner.isCurrent(action);
    void Promise.resolve().then(() => current() ? completeOidcBrowserCallback(current) : null).then((result) => {
      if (result && current()) onSuccess(result);
    }).catch((nextError: unknown) => {
      if (current()) setStatus({ context: owner.context, pending: "", error: nextError instanceof Error ? nextError.message : "Identity-provider sign-in failed." });
    });
    return () => { active = false; };
  }, [owner.context]);

  const showBuiltins = surface === "staff" || memberAccounts;
  const showGoogle = showBuiltins && Boolean(config?.google?.enabled);
  const showApple = showBuiltins && Boolean(config?.apple?.enabled);
  useEffect(() => {
    const host = googleHost.current;
    if (!host || !showGoogle || !hostCurrent() || pending) return;
    const action = googleOwner.capture();
    let active = true;
    const current = () => active && googleHost.current === host && hostCurrent() && googleOwner.isCurrent(action);
    host.replaceChildren();
    void mountGoogleButton(host, config?.google?.web_client_id ?? "", surface,
      (result) => { if (current()) onSuccess(result); },
      (nextError) => { if (current()) setGoogleError({ context: googleOwner.context, error: nextError.message }); },
      current,
    ).catch((nextError: unknown) => {
      if (current()) setGoogleError({ context: googleOwner.context, error: nextError instanceof Error ? nextError.message : "Google sign-in failed." });
    });
    return () => { active = false; host.replaceChildren(); };
  }, [config, surface, showGoogle, googleOwner.context, pending]);

  const oidcProviders = surface === "member" ? Object.entries(config ?? {}).filter(
    (entry): entry is [string, NonNullable<SocialConfig[`oidc:${string}`]>] =>
      entry[0].startsWith("oidc:") && Boolean(entry[1]?.enabled),
  ) : [];
  // Institution OIDC remains available with consumer member accounts switched off.
  if (!showGoogle && !showApple && oidcProviders.length === 0) return null;

  async function connect(provider: string) {
    if (!hostCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    const current = () => hostCurrent() && owner.isCurrent(action);
    setStatus({ context: action.context, error: "", pending: provider });
    setGoogleError({ context: googleOwner.context, error: "" });
    try {
      if (provider === "apple") {
        const result = await signInWithApple(config?.apple?.service_id ?? "", surface, current);
        if (!current()) return;
        if (owner.finish(action)) setStatus({ context: action.context, error: "", pending: "" });
        if (current()) onSuccess(result);
      } else {
        await beginOidcBrowser(provider.slice("oidc:".length), email, makerspaceSlug, current);
      }
    } catch (nextError) {
      if (current()) setStatus({ context: action.context, pending: "", error: nextError instanceof Error ? nextError.message : "Identity-provider sign-in failed." });
    } finally {
      // Only this active attempt can release the pending UI.
      if (owner.finish(action)) setStatus((state) => state.context === action.context ? { ...state, pending: "" } : state);
    }
  }

  return (
    <section className="mt-2 flex flex-col gap-4" aria-label="Social sign in">
      <div aria-hidden="true" className="flex items-center gap-3 text-caption text-ink-muted">
        <span className="h-px flex-1 bg-line" />or continue with<span className="h-px flex-1 bg-line" />
      </div>
      <div className="flex flex-col items-center gap-3">
        {showGoogle ? <div ref={googleHost} className="min-h-11 w-full max-w-full overflow-x-auto text-center" /> : null}
        {showApple ? (
          <Button variant="secondary" fullWidth disabled={disabled || Boolean(pending)} loading={pending === "apple"}
            loadingLabel="Connecting to Apple…" onClick={() => { void connect("apple"); }}>Continue with Apple</Button>
        ) : null}
        {oidcProviders.map(([key, provider]) => (
          <Button key={key} variant="secondary" fullWidth disabled={disabled || Boolean(pending)} loading={pending === key}
            loadingLabel={`Connecting to ${provider.display_name}…`} onClick={() => { void connect(key); }}>
            {`Continue with ${provider.display_name}`}
          </Button>
        ))}
      </div>
      <ErrorText message={error || (googleError.context === googleOwner.context ? googleError.error : "")} />
    </section>
  );
}
