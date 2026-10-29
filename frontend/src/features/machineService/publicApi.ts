import type {
  ApiPath, PublicMachineServiceStatus, PublicMachineServiceSubmit,
  PublicMachineServiceSubmitResponse, PublicMachineServiceType,
  PublicMachineServiceUpload, PublicMachineServiceUploadResponse,
} from "../../generated/api";
import { publicV1Request, tenantPublicRequest } from "../../lib/api";

export type ServiceType = PublicMachineServiceType;
export type ServiceStatus = PublicMachineServiceStatus;
export type ServiceIdentity = { name?: string; checkin_mid?: number };

const TYPES: ApiPath = "/api/v1/public/{makerspace_slug}/machine-service/types";
const UPLOADS: ApiPath = "/api/v1/public/{makerspace_slug}/machine-service/uploads";
const SUBMIT: ApiPath = "/api/v1/public/{makerspace_slug}/machine-service-requests";
const STATUS: ApiPath = "/api/v1/public/machine-service/requests/{public_token}/status";

function tenantEndpoint(path: ApiPath, slug: string) {
  return path.replace("/api/v1", "").replace("{makerspace_slug}", encodeURIComponent(slug));
}

export async function fetchServiceTypes(slug: string) {
  const all: ServiceType[] = [];
  for (let page = 1; ; page += 1) {
    const data = await tenantPublicRequest<{ results: ServiceType[]; next: string | null }>(
      slug, `${tenantEndpoint(TYPES, slug)}?page=${page}`,
    );
    all.push(...data.results);
    if (!data.next) return all;
  }
}

export function presignServiceUpload(slug: string, body: PublicMachineServiceUpload) {
  return tenantPublicRequest<PublicMachineServiceUploadResponse>(slug, tenantEndpoint(UPLOADS, slug), {
    method: "POST", body: JSON.stringify(body),
  });
}

export function submitServiceRequest(slug: string, body: PublicMachineServiceSubmit) {
  return tenantPublicRequest<PublicMachineServiceSubmitResponse>(slug, tenantEndpoint(SUBMIT, slug), {
    method: "POST", body: JSON.stringify(body),
  });
}

export function fetchServiceStatus(token: string) {
  return publicV1Request<ServiceStatus>(
    STATUS.replace("/api/v1", "").replace("{public_token}", encodeURIComponent(token)),
  );
}

export function serviceRequestPath(tenantPath: (path?: string) => string, typeId?: number) {
  return `${tenantPath("machine-service")}${typeId === undefined ? "" : `?type=${typeId}`}`;
}
