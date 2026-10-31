import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { API_V1_URL, deferred, field, json, mountServiceRoute, serviceNetwork, settle,
  type ServiceNetwork } from "../../test/serviceOwnershipHarness";
import { PublicRequestStatusPage } from "./PublicRequestStatusPage";

let net: ServiceNetwork;
beforeEach(() => { net = serviceNetwork(); });
afterEach(() => { net.dispose(); });
const reference = () => screen.getByLabelText("Request reference");

describe("borrow reference ownership on the same reused route element", () => {
  it("immediately replaces an edited reference when the URL token changes, before paint", async () => {
    const view = mountServiceRoute(net, <PublicRequestStatusPage />, "/m/a/service?token=old-reference");
    await screen.findByText("Current tool");
    field("Request reference", "unsent-private-edit");
    view.frames.length = 0;
    view.navigate("/m/a/service?token=new%2Freference");
    expect(reference()).toHaveValue("new/reference");
    expect(view.frames.length).toBeGreaterThan(0);
    for (const frame of view.frames) {
      expect(frame.inputs).toContain("new/reference");
      expect(frame.inputs).not.toContain("old-reference");
      expect(frame.inputs).not.toContain("unsent-private-edit");
    }
    await waitFor(() => expect(net.borrow).toHaveBeenCalledTimes(2));
    expect(net.borrow.mock.calls[1][0]).toBe(`${API_V1_URL}/public/requests/new%2Freference/status`);
    await screen.findByText("Current tool");
    field("Request reference", "another-unsent-edit");
    view.navigate("/m/a/service?token=%20new%2Freference%20");
    expect(reference()).toHaveValue("new/reference");
    // The exact URL context changed, while the normalized lookup/cache key stayed stable.
    expect(net.borrow).toHaveBeenCalledTimes(2);
  });

  it("clears the draft immediately on token removal and only sends a newly visible typed reference", async () => {
    const view = mountServiceRoute(net, <PublicRequestStatusPage />, "/m/a/service?token=private-a");
    await screen.findByText("Current tool");
    view.frames.length = 0;
    view.navigate("/m/a/service");
    expect(reference()).toHaveValue("");
    expect(screen.getByRole("button", { name: "Check status" })).toBeDisabled();
    expect(screen.queryByText("Current tool")).not.toBeInTheDocument();
    expect(view.frames.every((frame) => frame.inputs.includes("") && !frame.inputs.includes("private-a"))).toBe(true);
    expect(net.borrow).toHaveBeenCalledOnce();
    field("Request reference", "  visible / ? & + ref  ");
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    await waitFor(() => expect(net.borrow).toHaveBeenCalledTimes(2));
    expect(reference()).toHaveValue("visible / ? & + ref");
    expect(net.borrow.mock.calls[1][0]).toBe(`${API_V1_URL}/public/requests/visible%20%2F%20%3F%20%26%20%2B%20ref/status`);
    expect(net.borrow.mock.calls[1][1]?.body).toBeUndefined();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Phone")).not.toBeInTheDocument();
  });

  it("resets maker-private unsent drafts on A→B→A and sends B's exact visible lookup with B credentials", async () => {
    const view = mountServiceRoute(net, <PublicRequestStatusPage />, "/m/a/service");
    field("Request reference", "unsubmitted-A-secret");
    view.frames.length = 0;
    view.navigate("/m/b/service");
    expect(reference()).toHaveValue("");
    expect(view.frames.every((frame) => !frame.inputs.includes("unsubmitted-A-secret"))).toBe(true);
    field("Request reference", "B-specific-token");
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    await screen.findByText("Current tool");
    expect(net.borrow).toHaveBeenCalledOnce();
    expect(net.borrow.mock.calls[0][0]).toBe(`${API_V1_URL}/public/requests/B-specific-token/status`);
    expect(new Headers(net.borrow.mock.calls[0][1]?.headers).get("X-Publishable-Key")).toBe("public-b");
    expect(reference()).toHaveValue("B-specific-token");
    view.navigate("/m/a/service");
    expect(reference()).toHaveValue("");
    expect(screen.queryByText("Current tool")).not.toBeInTheDocument();
    expect(net.borrow.mock.calls.some(([url]) => url.includes("unsubmitted-A-secret"))).toBe(false);
  });

  it("keeps current loading/404/retry behavior and does not display an obsolete maker response", async () => {
    const old = deferred<Response>();
    net.borrow.mockReturnValueOnce(old.promise).mockResolvedValueOnce(json({ detail: "Missing" }, 404));
    const view = mountServiceRoute(net, <PublicRequestStatusPage />, "/m/a/service?token=held-a");
    await waitFor(() => expect(net.borrow).toHaveBeenCalledOnce());
    expect(screen.getByLabelText("Loading request status")).toBeVisible();
    view.navigate("/m/b/service?token=missing-b");
    expect(reference()).toHaveValue("missing-b");
    expect(await screen.findByText("No request matches that reference")).toBeVisible();
    await settle(() => old.resolve(json({ status: "accepted", created_at: "2026-10-01T09:00:00Z",
      items: [{ product_name: "Obsolete A tool", requested_quantity: 2 }] })));
    await waitFor(() => expect(view.client.getQueryState(["public-request-status", "a", "held-a"])?.status).toBe("success"));
    expect(screen.queryByText("Obsolete A tool")).not.toBeInTheDocument();
    expect(screen.getByText("No request matches that reference")).toBeVisible();
    expect(reference()).toHaveValue("missing-b");
    field("Request reference", "current-b");
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("Current tool")).toBeVisible();
    expect(net.borrow.mock.calls[2][0]).toBe(`${API_V1_URL}/public/requests/current-b/status`);
    expect(reference()).toHaveValue("current-b");
  });
});
