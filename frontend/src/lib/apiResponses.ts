import { apiError } from "./apiErrors";
import { getSessionGeneration } from "./apiSession";

// One owner survives fetch, decoding and retries. Only a request's own synchronous
// credential clear may advance it; a response must never adopt an external login/logout.
export type ApiResponseOwner = { generation: number };

export function requireCurrentSession(owner: ApiResponseOwner) {
  if (owner.generation !== getSessionGeneration()) {
    throw apiError(401, { code: "session_changed", detail: "Your session changed. Retry this action." });
  }
}

export async function readApiResponse<T>(
  response: Response,
  owner: ApiResponseOwner,
  kind: "json" | "blob",
  allowNoContent = false,
): Promise<T> {
  requireCurrentSession(owner);
  try {
    if (!response.ok) {
      throw apiError(response.status, await response.json().catch(() => ({})));
    }
    // DRF destroy responses have no JSON body. Their publication still belongs
    // to this request's session, just like a decoded payload.
    if (allowNoContent && response.status === 204) return undefined as T;
    return (await (kind === "blob" ? response.blob() : response.json())) as T;
  } finally {
    // Check failed decoding too: a stale parse/transport error is obsolete work.
    requireCurrentSession(owner);
  }
}
