import { tenantPublicRequest } from "../../lib/api";
import type { OwnRequestStatus } from "../../generated/api";
import type { PaginatedResponse, PublicRequestStatus } from "../../types/inventory";
import type { ServiceStatus } from "../machineService/publicApi";
import type { RequestKind } from "./requestCapabilities";

export type OwnHardwareRequest = OwnRequestStatus;
export type RequestStatus = Pick<PublicRequestStatus, "status" | "created_at" | "items"> | ServiceStatus;
export const ownRequestsKey = (slug: string, generation: number, kind: RequestKind, page: number) =>
  ["my-requests", slug, generation, kind, page] as const;
export const savedRequestKey = (slug: string, generation: number, kind: RequestKind, token: string) =>
  ["saved-request-status", slug, generation, kind, token] as const;

export function fetchOwnRequests(slug: string, kind: RequestKind, page: number, signal: AbortSignal) {
  const resource = kind === "hardware" ? "requests" : "machine-service-requests";
  return tenantPublicRequest<PaginatedResponse<OwnHardwareRequest | ServiceStatus>>(
    slug, `/public/${encodeURIComponent(slug)}/${resource}/mine?page=${page}`, { signal },
  );
}
export function fetchSavedRequest(slug: string, kind: RequestKind, token: string, signal: AbortSignal) {
  const resource = kind === "hardware" ? "requests" : "machine-service/requests";
  return tenantPublicRequest<RequestStatus>(
    slug, `/public/${resource}/${encodeURIComponent(token)}/status`, { signal },
  );
}
