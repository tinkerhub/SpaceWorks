import { API_URL, API_V1_URL } from "./apiConfig";
import { apiError, messageForStatus } from "./apiErrors";
import {
  authHeaders,
  cacheTenantPublishableKey,
  canRefreshAfterUnauthorized,
  expireStaffAuthSession,
  publicHeaders,
  refreshAccessToken,
  tenantPublishableKeys,
} from "./apiSession";
import type { StaffAuthUser, TenantBootstrap } from "./apiTypes";

export async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: await publicHeaders(),
  });

  if (!response.ok) {
    throw new Error(`${messageForStatus(response.status)} (${response.status})`);
  }

  return (await response.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return fetchJson<T>(`${API_URL}${path}`);
}

export async function publicV1Request<T>(
  path: string,
  options: RequestInit = {},
  publishableKey?: string,
): Promise<T> {
  const response = await fetch(`${API_V1_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(await publicHeaders(publishableKey)),
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }

  return (await response.json()) as T;
}

export async function bootstrapTenant(params: { tenant?: string; slug?: string }) {
  const search = new URLSearchParams();
  if (params.tenant) search.set("tenant", params.tenant);
  if (params.slug) search.set("slug", params.slug);
  const bootstrap = await publicV1Request<TenantBootstrap>(
    `/bootstrap?${search.toString()}`,
  );
  cacheTenantPublishableKey(
    bootstrap.makerspace.slug,
    bootstrap.public_api.publishable_key,
  );
  return bootstrap;
}

export async function tenantPublicRequest<T>(
  slug: string,
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const normalized = slug.trim();
  let publishableKey = tenantPublishableKeys.get(normalized);
  if (!publishableKey) {
    const bootstrap = await bootstrapTenant({ slug: normalized });
    publishableKey = bootstrap.public_api.publishable_key;
  }
  return publicV1Request<T>(path, options, publishableKey);
}

export async function fetchMe(): Promise<StaffAuthUser> {
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
  options: RequestInit = {},
  includePublicCredentials = false,
): Promise<Response> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const makeRequest = async () =>
    fetch(`${API_V1_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(includePublicCredentials ? await publicHeaders() : {}),
        ...authHeaders(),
        ...(options.headers ?? {}),
      },
    });

  let response = await makeRequest();

  if (response.status === 401 && canRefreshAfterUnauthorized(path)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await makeRequest();
      if (response.status === 401) {
        expireStaffAuthSession();
      }
    } else {
      expireStaffAuthSession();
    }
  }
  return response;
}

/** Fetch a binary/non-JSON authenticated resource as a Blob.
 *
 * `<img src>` cannot carry an Authorization header, so an authenticated image has to be
 * fetched and handed to the DOM as an object URL. Callers must revoke that URL.
 */
export async function staffRequestBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const response = await staffFetch(path, options);
  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  return await response.blob();
}

export async function staffRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await staffFetch(path, options);

  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  // 204 No Content (e.g. DRF destroy) has an empty body - parsing it as JSON
  // would throw and surface a successful mutation as a failure.
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function memberRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await staffFetch(path, options, true);
  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function downloadStaffFile(path: string, filename: string) {
  const response = await fetch(`${API_V1_URL}${path}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
