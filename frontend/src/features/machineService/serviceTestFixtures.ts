import type { ServiceStatus, ServiceType } from "./publicApi";

export const genericType: ServiceType = {
  id: 11, name: "Laser cutter", icon: "", is_printer: false,
  file_policy: { allowed_extensions: ["pdf", "dxf"], allowed_mimes: ["application/pdf", "application/dxf"], max_bytes: 10 * 1024 * 1024 },
  materials: [], colors: [], consumable_pools: [],
};
export const printerType: ServiceType = {
  id: 22, name: "3D Printer", icon: "", is_printer: true,
  file_policy: { allowed_extensions: ["stl", "png", "pdf"], allowed_mimes: ["model/stl", "image/png", "application/pdf"], max_bytes: 50 * 1024 * 1024 },
  materials: ["PLA", "PETG"], colors: ["Blue", "Black"],
  consumable_pools: [{ id: 31, material: "PLA", color: "Blue" }],
};
export const serviceStatus: ServiceStatus = {
  public_token: "private-token", title: "Project enclosure", status: "pending",
  created_at: "2026-10-01T09:00:00Z", accepted_at: null, started_at: null, completed_at: null,
  estimated_minutes: 0, queue_position: 1, queue_approved_ahead: 0, queue_awaiting_review_ahead: 0,
};
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
