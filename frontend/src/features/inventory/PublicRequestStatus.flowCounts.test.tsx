import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { hardware, json, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { PublicRequestStatusPage } from "./PublicRequestStatusPage";

let net: ReturnType<typeof requestHistoryNetwork>;
beforeEach(() => { net = requestHistoryNetwork(); });
afterEach(() => net.dispose());
const mount = () => net.mount(<Routes><Route path="/m/:slug/request" element={<PublicRequestStatusPage />} /></Routes>, "/m/a/request?token=partial");

describe("public hardware status uses request flow quantities", () => {
  it("distinguishes requested, partially approved, issued and partially returned quantities", async () => {
    net.status.mockImplementation(async () => json(hardware("partial")));
    mount(); await screen.findByText("Tool partial");
    const item = within(screen.getByText("Tool partial").closest("li")!);
    for (const [label, value] of [["Requested", "9"], ["Approved", "6"], ["Handed out", "4"], ["Returned", "2"]]) {
      expect(item.getByText(label).parentElement?.querySelector("dd")).toHaveTextContent(value);
    }
    expect(screen.getByText("Some items are back; the rest are still out.")).toBeVisible();
    expect(net.status).toHaveBeenCalledOnce();
  });

  it("shows only requested for legacy rows missing flow counts, while preserving genuine zeros", async () => {
    net.status.mockImplementation(async () => json({ ...hardware("partial", "accepted"), items: [
      { product_name: "Legacy tool", requested_quantity: 3 },
      { product_name: "Not yet handed out", requested_quantity: 7, accepted_quantity: 2, issued_quantity: 0, returned_quantity: 0 },
    ] }));
    mount(); await screen.findByText("Legacy tool");
    const legacy = within(screen.getByText("Legacy tool").closest("li")!);
    expect(legacy.getByText("Requested").parentElement?.querySelector("dd")).toHaveTextContent("3");
    for (const label of ["Approved", "Handed out", "Returned"]) expect(legacy.queryByText(label)).not.toBeInTheDocument();
    const current = within(screen.getByText("Not yet handed out").closest("li")!);
    for (const label of ["Handed out", "Returned"]) expect(current.getByText(label).parentElement?.querySelector("dd")).toHaveTextContent("0");
  });
});
