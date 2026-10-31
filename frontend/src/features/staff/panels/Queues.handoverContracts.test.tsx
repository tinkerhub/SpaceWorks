import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { Queues } from "./Queues";
import {
  field, containers, countedRequest, dialog, endHardwareTest, hardwareHttp, held, json,
  maker, mountHardware, page, queueAction, release, requestA, scanAsset,
  setValue, startHardwareTest, uploadPhoto, waitForChoice,
} from "../../../test/hardwareOwnershipHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);
const panel = () => <Queues makerspace={maker} guestOnly={false} canIssueRequest canReturnRequest canReviewRequests />;

it("held list populated during a failed assignment re-enables with options without another GET", async () => {
  const list = held<Response>(); const assignment = held<Response>(); let reads = 0;
  const net = hardwareHttp((call) => call.method === "GET" && call.path.includes("/containers") ? (++reads, list.promise)
    : call.path.endsWith("/assign-box") ? assignment.promise : undefined, [countedRequest]);
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  fireEvent.click(screen.getByRole("checkbox", { name: /^Use a container/ }));
  await waitFor(() => expect(reads).toBe(1));
  fireEvent.click(dialog().getByRole("button", { name: "Enter code manually" }));
  setValue("Container code", "BOX-A");
  await uploadPhoto();
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await waitFor(() => expect(net.calls.some((call) => call.path.endsWith("/assign-box"))).toBe(true));
  await release(list, json(page(containers)));
  await waitForChoice("Available container", "BOX-B");
  expect(field("Available container")).toBeDisabled();
  await release(assignment, json({ detail: "Container temporarily busy" }, 409));
  await screen.findAllByText("Container temporarily busy");
  await waitFor(() => expect(field("Available container")).toBeEnabled());
  setValue("Available container", "BOX-B");
  expect(field("Container code")).toHaveValue("BOX-B");
  expect(reads).toBe(1);
  expect(net.calls.some((call) => call.path.endsWith("/issue"))).toBe(false);
});

it("assigned container, photo, scans and remark survive failed issue; explicit retry issues once without reassignment", async () => {
  let attempts = 0;
  const net = hardwareHttp((call) => call.path.endsWith("/issue") && ++attempts === 1
    ? json({ detail: "Issue service busy" }, 409) : undefined, [requestA]);
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  fireEvent.click(screen.getByRole("checkbox", { name: /^Use a container/ }));
  await waitForChoice("Available container", "BOX-A");
  setValue("Available container", "BOX-A");
  setValue("Remark", "Both units photographed");
  await uploadPhoto();
  await scanAsset("UNIT-1");
  await screen.findByRole("button", { name: "Remove UNIT-1" });
  await scanAsset("UNIT-2");
  await screen.findByRole("button", { name: "Remove UNIT-2" });
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await screen.findByText(/Container assigned, but issue failed: Issue service busy/);
  await waitFor(() => expect(field("Remark")).toBeEnabled());
  expect(field("Remark")).toHaveValue("Both units photographed");
  expect(screen.getByText("Photo uploaded")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Asset QR codes (2/2)" })).toBeVisible();
  expect(screen.getByText("BOX-A")).toBeVisible();
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await screen.findByText("Request #1 issued.");
  expect(net.calls.filter((call) => call.path.endsWith("/assign-box"))).toHaveLength(1);
  const issues = net.calls.filter((call) => call.path.endsWith("/issue"));
  expect(issues).toHaveLength(2);
  expect(issues[1].body).toEqual(issues[0].body);
  expect(issues[1].body).toEqual({ evidence_id: 71, remark: "Both units photographed", rejects: [], asset_qr_payloads: ["UNIT-1", "UNIT-2"] });
});

it("an existing assigned container still requires its code and issue evidence", async () => {
  const net = hardwareHttp(undefined, [{ ...countedRequest, assigned_box_id: 31, assigned_box_label: "Blue container" }]);
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A");
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  expect(screen.getByText("Scan or choose a container before issuing.")).toBeVisible();
  await waitForChoice("Available container", "BOX-A");
  setValue("Available container", "BOX-A");
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  expect(screen.getByText("Upload an issue photo before issuing.")).toBeVisible();
  expect(net.calls.some((call) => call.path.endsWith("/issue"))).toBe(false);
  await uploadPhoto();
  fireEvent.click(dialog().getByRole("button", { name: "Issue" }));
  await screen.findByText("Request #1 issued.");
  expect(net.calls.find((call) => call.path.endsWith("/assign-box"))?.body).toEqual({ box_code: "BOX-A" });
});

it("current reviewed return preserves photo, remark, matching-container and per-unit outcome requirements", async () => {
  const row = { ...requestA, status: "issued", assigned_box_id: 31, assigned_box_label: "Blue container",
    items: requestA.items.map((item) => ({ ...item, issued_quantity: 2,
      issued_assets: [{ asset_id: 51, asset_tag: "UNIT-1", serial_number: "" }, { asset_id: 52, asset_tag: "UNIT-2", serial_number: "" }] })) };
  const net = hardwareHttp(undefined, [row]);
  mountHardware(panel());
  await screen.findByText("Borrower A");
  queueAction("Borrower A", "Return");
  fireEvent.click(dialog().getByRole("button", { name: "Submit return" }));
  expect(screen.getByText("Upload a return photo before submitting.")).toBeVisible();
  await uploadPhoto("Return photo");
  fireEvent.click(dialog().getByRole("button", { name: "Submit return" }));
  expect(screen.getByText("Return remark is required.")).toBeVisible();
  setValue("Remark", "One unit damaged");
  fireEvent.click(dialog().getByRole("button", { name: "Submit return" }));
  expect(screen.getByText("Scan or choose the loan's container before submitting.")).toBeVisible();
  await waitForChoice("Available container", "BOX-A");
  setValue("Available container", "BOX-A");
  setValue("UNIT-2", "damaged");
  fireEvent.click(dialog().getByRole("button", { name: "Submit return" }));
  await screen.findByText("Return recorded for request #1.");
  expect(net.calls.find((call) => call.path.endsWith("/return"))?.body).toEqual({ evidence_id: 71, box_code: "BOX-A", remark: "One unit damaged",
    resolutions: [{ item_id: 21, returned: 1, damaged: 1, missing: 0, assets: [{ asset_id: 51, outcome: "returned" }, { asset_id: 52, outcome: "damaged" }] }] });
});
