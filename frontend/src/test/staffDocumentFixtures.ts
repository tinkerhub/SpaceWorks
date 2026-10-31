import type { Warranty } from "../features/staff/warrantyApi";
import type { MachineDocument } from "../features/staff/machinesApi";
import type { MaintenanceDocument } from "../features/staff/panels/machine/maintenanceApi";

export function warrantyFixture(hostId = 1): Warranty {
  return {
    id: hostId + 40, host_kind: "machine", host_id: hostId, host_label: `Machine ${hostId}`,
    asset_id: null, asset_tag: null, serial_number: null, printer_id: null, printer_name: null,
    printer_model: null, machine_id: hostId, machine_name: `Machine ${hostId}`,
    purchased_on: "2026-01-02", warranty_expires_on: "2027-01-02", vendor_name: "Existing vendor",
    vendor_contact: "Private existing contact", status: "active", documents: [],
  };
}
export const machineDocument: MachineDocument = {
  id: 81, doc_type: "manual", original_filename: "existing.pdf",
  content_type: "application/pdf", size_bytes: 12, created_at: "2026-01-02T00:00:00Z",
};
export const maintenanceDocument: MaintenanceDocument = {
  id: 81, log_id: 11, object_key: "private/maintenance", size_bytes: 12,
  uploaded_by_id: 1, created_at: "2026-01-02T00:00:00Z",
};
