import { getSessionGeneration } from "../../lib/apiSession";
import { publicV1Request } from "../../lib/api";

export type SocialProvider = "google" | "apple";
export type SocialSurface = "member" | "staff";
export type SocialLoginResult = {
  access: string;
  user: Record<string, unknown>;
  outcome: "created" | "existing" | "auto_linked";
};
export type SocialConfig = {
  google?: { enabled: boolean; web_client_id: string };
  apple?: { enabled: boolean; service_id: string };
  [provider: `oidc:${string}`]:
    | { enabled: boolean; display_name: string; client_id: string; issuer: string }
    | undefined;
};

type OidcStartResult = {
  authorization_url: string;
  state: string;
  nonce: string;
};

type OwnershipCheck = () => boolean;
function ownershipCheck(isOwned: OwnershipCheck = () => true) {
  const epoch = getSessionGeneration();
  return () => epoch === getSessionGeneration() && isOwned();
}
function requireOwnership(isOwned: OwnershipCheck) {
  if (!isOwned()) throw new Error("Sign-in is no longer active. Please try again.");
}

const OIDC_NONCE_PREFIX = "spaceworks.oidc.nonce.";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: Record<string, unknown>): void;
          renderButton(element: HTMLElement, options: Record<string, unknown>): void;
        };
      };
    };
    AppleID?: {
      auth: {
        init(options: Record<string, unknown>): void;
        signIn(): Promise<{ authorization: { id_token: string }; user?: { name?: { firstName?: string; lastName?: string } } }>;
      };
    };
  }
}

const scripts = new Map<string, Promise<void>>();

function loadScript(src: string) {
  const existing = scripts.get(src);
  if (existing) return existing;
  const pending = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Unable to load the identity provider."));
    document.head.appendChild(script);
  });
  scripts.set(src, pending);
  return pending;
}

async function requestNonce(provider: SocialProvider, surface: SocialSurface) {
  return publicV1Request<{ nonce: string }>("/auth/social/nonce", {
    method: "POST",
    body: JSON.stringify({
      provider,
      surface,
      delivery: "web",
      client_platform: "web",
    }),
  });
}

async function complete(provider: SocialProvider, surface: SocialSurface, idToken: string, nonce: string, appleName = "") {
  return publicV1Request<SocialLoginResult>(`/auth/social/${provider}`, {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({
      id_token: idToken,
      nonce,
      surface,
      delivery: "web",
      client_platform: "web",
      ...(appleName ? { apple_name: appleName } : {}),
    }),
  });
}

export async function mountGoogleButton(
  element: HTMLElement,
  clientId: string,
  surface: SocialSurface,
  onSuccess: (result: SocialLoginResult) => void,
  onError: (error: Error) => void,
  isOwned?: OwnershipCheck,
) {
  const current = ownershipCheck(isOwned);
  requireOwnership(current);
  const { nonce } = await requestNonce("google", surface);
  requireOwnership(current);
  await loadScript("https://accounts.google.com/gsi/client");
  requireOwnership(current);
  if (!window.google) throw new Error("Google sign-in is unavailable.");
  let exchanging = false;
  window.google.accounts.id.initialize({
    client_id: clientId,
    nonce,
    callback: async ({ credential }: { credential?: string }) => {
      if (!current() || exchanging) return;
      if (!credential) return onError(new Error("Google sign-in was cancelled."));
      try {
        exchanging = true;
        requireOwnership(current);
        const result = await complete("google", surface, credential, nonce);
        if (current()) onSuccess(result);
      } catch (error) {
        if (current()) onError(error instanceof Error ? error : new Error("Google sign-in failed."));
      } finally {
        exchanging = false;
      }
    },
  });
  window.google.accounts.id.renderButton(element, {
    type: "standard",
    theme: "outline",
    size: "large",
    width: Math.min(360, element.clientWidth || 320),
  });
}

export async function signInWithApple(serviceId: string, surface: SocialSurface, isOwned?: OwnershipCheck) {
  const current = ownershipCheck(isOwned);
  requireOwnership(current);
  const { nonce } = await requestNonce("apple", surface);
  requireOwnership(current);
  await loadScript("https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js");
  requireOwnership(current);
  if (!window.AppleID) throw new Error("Apple sign-in is unavailable.");
  window.AppleID.auth.init({
    clientId: serviceId,
    scope: "name email",
    redirectURI: window.location.origin,
    usePopup: true,
    nonce,
  });
  const result = await window.AppleID.auth.signIn();
  requireOwnership(current);
  const name = [result.user?.name?.firstName, result.user?.name?.lastName].filter(Boolean).join(" ");
  const completed = await complete("apple", surface, result.authorization.id_token, nonce, name);
  requireOwnership(current);
  return completed;
}

export async function beginOidcBrowser(
  slug: string,
  email: string,
  makerspaceSlug: string,
  isOwned?: OwnershipCheck,
) {
  const current = ownershipCheck(isOwned);
  requireOwnership(current);
  const redirectUri = `${window.location.origin}${window.location.pathname}`;
  const started = await publicV1Request<OidcStartResult>(
    `/auth/social/oidc/${encodeURIComponent(slug)}/authorize`,
    {
      method: "POST",
      body: JSON.stringify({
        redirect_uri: redirectUri,
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(makerspaceSlug ? { makerspace_slug: makerspaceSlug } : {}),
      }),
    },
  );
  requireOwnership(current);
  try {
    window.sessionStorage.setItem(`${OIDC_NONCE_PREFIX}${started.state}`, started.nonce);
  } catch {
    throw new Error("Browser storage is required for secure identity-provider sign-in.");
  }
  requireOwnership(current);
  window.location.assign(started.authorization_url);
}

export async function completeOidcBrowserCallback(isOwned?: OwnershipCheck): Promise<SocialLoginResult | null> {
  const current = ownershipCheck(isOwned);
  requireOwnership(current);
  const query = new URLSearchParams(window.location.search);
  const code = query.get("code")?.trim() ?? "";
  const state = query.get("state")?.trim() ?? "";
  if (!code && !state && !query.get("error")) return null;
  if (!code || !state || query.get("error")) {
    clearOidcQuery();
    throw new Error("Identity-provider sign-in was cancelled or refused.");
  }
  let nonce = "";
  try {
    nonce = window.sessionStorage.getItem(`${OIDC_NONCE_PREFIX}${state}`) ?? "";
    window.sessionStorage.removeItem(`${OIDC_NONCE_PREFIX}${state}`);
  } catch {
    // The backend still refuses the callback because the nonce is mandatory.
  }
  clearOidcQuery();
  if (!nonce) throw new Error("Identity-provider sign-in expired. Please try again.");
  requireOwnership(current);
  const result = await publicV1Request<SocialLoginResult>("/auth/social/oidc/callback", {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({ code, state, nonce }),
  });
  requireOwnership(current);
  return result;
}

function clearOidcQuery() {
  const url = new URL(window.location.href);
  for (const key of ["code", "state", "session_state", "iss", "error", "error_description"]) {
    url.searchParams.delete(key);
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}
