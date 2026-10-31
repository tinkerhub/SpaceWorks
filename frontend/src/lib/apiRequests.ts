import { API_URL, API_V1_URL } from "./apiConfig";
import { messageForStatus, StructuredApiError } from "./apiErrors";
import { readApiResponse, requireCurrentSession, type ApiResponseOwner } from "./apiResponses";
import {
  authHeaders,
  cacheTenantPublishableKey,
  canRefreshAfterUnauthorized,
  clearAccessToken,
  expireStaffAuthSession,
  getAccessToken,
  getSessionGeneration,
  publicHeaders,
  refreshAccessToken,
  tenantPublishableKeys,
} from "./apiSession";
import type { StaffAuthUser, TenantBootstrap } from "./apiTypes";

export async function fetchJson<T>(url: string): Promise<T> {
  const owner = { generation: getSessionGeneration() };
  try {
    const headers = await publicHeaders();
    requireCurrentSession(owner);
    const response = await fetch(url, { headers });
    requireCurrentSession(owner);
    if (!response.ok) {
      throw new Error(`${messageForStatus(response.status)} (${response.status})`);
    }
    return await readApiResponse<T>(response, owner, "json");
  } finally {
    requireCurrentSession(owner);
  }
}

export function apiGet<T>(path: string): Promise<T> {
  return fetchJson<T>(`${API_URL}${path}`);
}

export async function publicV1Request<T>(
  path: string,
  options: RequestInit = {},
  publishableKey?: string,
): Promise<T> {
  const owner = { generation: getSessionGeneration() };
  try {
    const headers = await publicHeaders(publishableKey);
    requireCurrentSession(owner);
    return await publicJsonRequest<T>(path, options, headers, owner);
  } finally {
    requireCurrentSession(owner);
  }
}

async function publicJsonRequest<T>(
  path: string,
  options: RequestInit,
  publicCredentials: HeadersInit,
  owner: ApiResponseOwner,
): Promise<T> {
  requireCurrentSession(owner);
  const response = await fetch(`${API_V1_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...publicCredentials,
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });
  requireCurrentSession(owner);
  return readApiResponse<T>(response, owner, "json");
}

export async function bootstrapTenant(params: { tenant?: string; slug?: string }) {
  const owner = { generation: getSessionGeneration() };
  try {
    const search = new URLSearchParams();
    if (params.tenant) search.set("tenant", params.tenant);
    if (params.slug) search.set("slug", params.slug);
    const bootstrap = await publicV1Request<TenantBootstrap>(
      `/bootstrap?${search.toString()}`,
    );
    requireCurrentSession(owner);
    cacheTenantPublishableKey(
      bootstrap.makerspace.slug,
      bootstrap.public_api.publishable_key,
    );
    return bootstrap;
  } finally {
    requireCurrentSession(owner);
  }
}

export function tenantPublicRequest<T>(
  slug: string,
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return tenantPublicRequestWithRetry(slug, (headers, owner) => publicJsonRequest<T>(path, options, headers, owner));
}

async function tenantPublicRequestWithRetry<T>(
  slug: string,
  request: (publicCredentials: HeadersInit, owner: ApiResponseOwner) => Promise<T>,
): Promise<T> {
  const owner = { generation: getSessionGeneration() };
  try {
    const normalized = slug.trim();
    let publishableKey = tenantPublishableKeys.get(normalized);
    if (!publishableKey) {
      const bootstrap = await bootstrapTenant({ slug: normalized });
      requireCurrentSession(owner);
      publishableKey = bootstrap.public_api.publishable_key;
    } else {
      cacheTenantPublishableKey(normalized, publishableKey);
    }
    // Resolve credentials once so a guarded retry reaches fetch without another await.
    const publicCredentials = await publicHeaders(publishableKey);
    requireCurrentSession(owner);
    try {
      const result = await request(publicCredentials, owner);
      requireCurrentSession(owner);
      return result;
    } catch (error) {
      requireCurrentSession(owner);
      // A signed-in member who reloaded holds no access token until the refresh cookie is
      // exchanged; without this every account-only public action would 401 after a reload.
      const unauthorized = error instanceof StructuredApiError && error.status === 401;
      if (!unauthorized) throw error;
      const refreshed = await refreshAccessToken();
      requireCurrentSession(owner);
      if (refreshed) return await request(publicCredentials, owner);
      // The held token is dead and cannot be renewed: drop it, or every later public call on
      // this page keeps sending it, and retry once anonymously so open routes still answer.
      if (!getAccessToken()) throw error;
      clearAccessToken();
      // No await between our own clear and adoption; later external changes still lose ownership.
      owner.generation = getSessionGeneration();
      requireCurrentSession(owner);
      return await request(publicCredentials, owner);
    }
  } finally {
    requireCurrentSession(owner);
  }
}

export function tenantPublicRequestBlob(slug: string, path: string): Promise<Blob> {
  return tenantPublicRequestWithRetry(slug, async (publicCredentials, owner) => {
    requireCurrentSession(owner);
    const response = await fetch(`${API_V1_URL}${path}`, {
      headers: { ...publicCredentials, ...authHeaders() },
    });
    requireCurrentSession(owner);
    return readApiResponse<Blob>(response, owner, "blob");
  });
}

export function fetchMe(): Promise<StaffAuthUser> {
  return staffRequest<StaffAuthUser>("/auth/me");
}

/** The authenticated request, up to but not including reading the body.
 *
 * Extracted so a non-JSON response (an SVG, say) can reuse the refresh-and-retry
 * behaviour rather than carrying a second copy of it. A duplicated refresh path is how one
 * caller silently stops recovering from an expired token.
 */
async function staffFetch(
  path: string,
  options: RequestInit,
  includePublicCredentials: boolean,
  owner: ApiResponseOwner,
): Promise<Response> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const publicCredentials = includePublicCredentials ? await publicHeaders() : {};
  requireCurrentSession(owner);
  const makeRequest = () =>
    fetch(`${API_V1_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...publicCredentials,
        ...authHeaders(),
        ...(options.headers ?? {}),
      },
    });

  let response = await makeRequest();
  requireCurrentSession(owner);

  if (response.status === 401 && canRefreshAfterUnauthorized(path)) {
    const refreshed = await refreshAccessToken();
    requireCurrentSession(owner);
    if (refreshed) {
      response = await makeRequest();
      requireCurrentSession(owner);
    }
    if (!refreshed || response.status === 401) {
      // Expiry clears exactly once before notifying listeners. Adopt that clear only:
      // a synchronous listener that signs in/out must still invalidate this response.
      owner.generation += 1;
      expireStaffAuthSession();
      requireCurrentSession(owner);
    }
  }
  return response;
}

async function authenticatedResponse<T>(
  path: string,
  options: RequestInit,
  includePublicCredentials: boolean,
  kind: "json" | "blob",
): Promise<T> {
  const owner = { generation: getSessionGeneration() };
  try {
    const response = await staffFetch(path, options, includePublicCredentials, owner);
    return await readApiResponse<T>(response, owner, kind, kind === "json");
  } finally {
    // Network failures also belong to their dispatch session. Preserve genuine 401s
    // after our own expiry, but never publish an outcome under a newer account.
    requireCurrentSession(owner);
  }
}

/** Fetch a binary/non-JSON authenticated resource as a Blob.
 *
 * `<img src>` cannot carry an Authorization header, so an authenticated image has to be
 * fetched and handed to the DOM as an object URL. Callers must revoke that URL.
 */
export function staffRequestBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  return authenticatedResponse<Blob>(path, options, false, "blob");
}

export function staffRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return authenticatedResponse<T>(path, options, false, "json");
}

export function memberRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return authenticatedResponse<T>(path, options, true, "json");
}

export function memberRequestBlob(path: string): Promise<Blob> {
  return authenticatedResponse<Blob>(path, {}, true, "blob");
}

export async function downloadStaffFile(path: string, filename: string) {
  const owner = { generation: getSessionGeneration() };
  const blob = await staffRequestBlob(path);
  requireCurrentSession(owner);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
