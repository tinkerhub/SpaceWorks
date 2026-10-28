import type { Machine } from "../../machinesApi";

export const testMachine: Machine = {
  id: 41, makerspace: 1, name: "Workshop printer", status: "idle",
  machine_type: {
    id: 2, slug: "3d_printer", name: "3D printers", icon: "", makerspace: null,
    is_builtin: true, managing_action: "manage_printing",
    capability_config: { metering_unit: "weight", requires_booking: false },
  },
  location: "Bench", notes: "", firmware_version: "", camera_feed_url: "",
  image_url: null, warranty_status: "unknown", is_public: true, is_active: true,
  usage_hours: "0", can_operate: true, can_edit: true, can_delegate: true,
  can_retire: true, can_unretire: false, can_manage: true, created_at: "", updated_at: "",
};
