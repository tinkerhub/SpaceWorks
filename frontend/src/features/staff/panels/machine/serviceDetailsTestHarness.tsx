import { fireEvent, screen } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import type { MachineServiceRequest, ServiceFile } from "../../../../generated/api";
import { serviceJob } from "../../../../test/staffServiceOwnershipHarness";
import { mountStaff } from "../../../../test/staffUploadHarness";
import { ServiceRequestDetails } from "./ServiceRequestDetails";

export const attachment: ServiceFile = {
  id: 81, kind: "design", original_filename: "fixture.stl", content_type: "model/stl",
  size_bytes: 123, created_at: "2026-11-01", attached_at: "2026-11-01",
};
export const detailedJob: MachineServiceRequest = {
  ...serviceJob(), files: [attachment], description: "Cut two tabs.\nKeep the offcuts.",
  source_link: "https://design.test/project", requester_name: "Ada", assigned_machine: { id: 12, name: "Assigned press", status: "idle" },
  machine: { id: 11, name: "Legacy bucket", status: "idle" },
};
export function DetailsVisit({ request = detailedJob, makerspaceId = 1 }: { request?: MachineServiceRequest; makerspaceId?: number }) {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/admin/machines/2-printer/queue")}>Other type</button>
    <button onClick={() => navigate("/admin/machines/1-press/queue")}>Original type</button>
    <ServiceRequestDetails makerspaceId={makerspaceId} request={request} /></>;
}
export function detailsTree(request = detailedJob, makerspaceId = 1) {
  return <MemoryRouter initialEntries={["/admin/machines/1-press/queue"]}>
    <DetailsVisit request={request} makerspaceId={makerspaceId} />
  </MemoryRouter>;
}
export function mountDetails(request = detailedJob) { return mountStaff(detailsTree(request)); }
export function expandDetails() {
  const summary = screen.getByText("Project details & files", { selector: "summary" });
  if (!summary.parentElement?.hasAttribute("open")) fireEvent.click(summary);
}
