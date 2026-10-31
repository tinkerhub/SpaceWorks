import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, hardware, json, machine, page, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { MyRequestsPage } from "./MyRequestsPage";

let net: ReturnType<typeof requestHistoryNetwork>;
afterEach(() => net.dispose());
function start(modules?: string[]) {
  net = requestHistoryNetwork({ accounts: true, modules });
  setAccessToken(accessToken("account-one"));
}
const mount = () => net.mount(<Routes><Route path="/m/:slug/my-requests" element={<MyRequestsPage />} /></Routes>);
const branch = (kind: "Hardware" | "Machine service") => within(screen.getByRole("region", { name: `${kind} requests` }));

describe("real account history transport and presentation", () => {
  it("paginates hardware and machine branches by 24 independently, constructing only local page URLs", async () => {
    start();
    net.mine.mockImplementation(async (url) => {
      const second = url.searchParams.get("page") === "2";
      const isMachine = url.pathname.includes("machine-service");
      const results = second ? [isMachine ? machine("machine-25") : hardware("hardware-25")]
        : Array.from({ length: 24 }, (_, index) => isMachine ? machine(`machine-${index + 1}`) : hardware(`hardware-${index + 1}`));
      return json(page(results, 25, second ? null : "https://attacker.example/private?name=Ada"));
    });
    mount();
    await screen.findByText("Tool hardware-24"); await screen.findByText("Project machine-24");
    const hw = branch("Hardware"), ms = branch("Machine service");
    expect(hw.getAllByRole("link", { name: "Open private status link" })).toHaveLength(24);
    expect(ms.getAllByRole("link", { name: "Open private status link" })).toHaveLength(24);
    expect(hw.getByText(/25 requests · Page 1 · Up to 24/)).toBeVisible();
    expect(hw.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(hw.getByRole("button", { name: "Next" }));
    await screen.findByText("Tool hardware-25");
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(ms.getByText("Project machine-1")).toBeVisible();
    expect(hw.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(hw.getByRole("link", { name: "Open private status link" })).toHaveAttribute("href", "/m/a/request?token=hardware-25");
    expect(ms.getAllByRole("link", { name: "Open private status link" })[0]).toHaveAttribute("href", "/m/a/machine-service?token=machine-1");
    fireEvent.click(ms.getByRole("button", { name: "Next" }));
    await screen.findByText("Project machine-25");
    fireEvent.click(hw.getByRole("button", { name: "Previous" }));
    await screen.findByText("Tool hardware-1");
    expect(net.mine.mock.calls.map(([url]) => url.pathname + url.search).sort()).toEqual([
      "/api/v1/public/a/machine-service-requests/mine?page=1", "/api/v1/public/a/machine-service-requests/mine?page=2",
      "/api/v1/public/a/requests/mine?page=1", "/api/v1/public/a/requests/mine?page=2",
    ]);
    expect(net.fetch.mock.calls.every(([url]) => !String(url).includes("attacker.example"))).toBe(true);
    for (const [, init] of net.mine.mock.calls) {
      expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${accessToken("account-one")}`);
      expect(new Headers(init?.headers).get("X-Publishable-Key")).toBe("public-a");
    }
    expect(net.other).not.toHaveBeenCalled();
  });

  it.each(["request_workflow", "machine_service"])("never calls the off branch when only %s is enabled", async (module) => {
    start([module]); mount();
    await screen.findByText(module === "request_workflow" ? "Tool hardware-1" : "Project machine-1");
    expect(net.mine).toHaveBeenCalledOnce();
    expect(net.mine.mock.calls[0][0].pathname).toContain(module === "request_workflow" ? "/requests/mine" : "/machine-service-requests/mine");
    expect(screen.queryByRole("region", { name: module === "request_workflow" ? "Machine service requests" : "Hardware requests" })).not.toBeInTheDocument();
  });

  it.each(["hardware", "machine"])("keeps the other branch usable after a %s 404, then retries independently", async (failed) => {
    start();
    let fail = true;
    net.mine.mockImplementation(async (url) => {
      const isMachine = url.pathname.includes("machine-service");
      return fail && isMachine === (failed === "machine") ? json({ detail: "Gone" }, 404)
        : json(page([isMachine ? machine() : hardware()]));
    });
    mount();
    expect(await screen.findByText("These requests are unavailable here.")).toBeVisible();
    expect(await screen.findByText(failed === "machine" ? "Tool hardware-1" : "Project machine-1")).toBeVisible();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText(failed === "machine" ? "Project machine-1" : "Tool hardware-1");
    expect(net.mine).toHaveBeenCalledTimes(3);
  });

  it("shows exact per-request quantities and excludes unrelated PII, evidence, staff reasons and cancel actions", async () => {
    start(); net.mine.mockImplementation(async (url) => json(page([url.pathname.includes("machine-service") ? machine() : hardware("owned", "cancelled")]))); mount();
    const region = branch("Hardware");
    await region.findByText("Cancelled");
    const values = { Requested: "9", Approved: "6", "Handed out": "4", Returned: "2" };
    for (const [label, value] of Object.entries(values)) expect(region.getByText(label).parentElement).toHaveTextContent(value);
    expect(screen.queryByText(/Private staff reason|other@example.com|unrelated-person|private-photo.jpg/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /cancel/i })).not.toBeInTheDocument();
  });

  it("reports a typed account denial without using a public identity or roster fallback", async () => {
    start(); net.mine.mockImplementation(async () => json({ detail: "Forbidden" }, 403)); mount();
    await waitFor(() => expect(screen.getAllByText("This account cannot access this request history.")).toHaveLength(2));
    expect(net.mine).toHaveBeenCalledTimes(2); expect(net.status).not.toHaveBeenCalled();
    expect(net.other).not.toHaveBeenCalled();
  });

  it("retains private status links throughout the hardware lifecycle", async () => {
    start(["request_workflow"]);
    const states = [
      ["draft", "Draft"], ["pending_approval", "Pending approval"], ["accepted", "Accepted"],
      ["rejected", "Rejected"], ["cancelled", "Cancelled"], ["issued", "Issued"],
      ["partially_returned", "Partially returned"], ["returned", "Returned"], ["closed_with_issue", "Closed with issue"],
    ];
    net.mine.mockResolvedValueOnce(json(page(states.map(([status]) => hardware(status, status)))));
    mount(); await screen.findByText("Tool closed_with_issue");
    for (const [status, label] of states) {
      const row = screen.getByText(`Tool ${status}`).closest("ul")?.closest("div")?.parentElement;
      expect(row).toHaveTextContent(label);
      expect(branch("Hardware").getAllByRole("link", { name: "Open private status link" }).some((link) =>
        link.getAttribute("href") === `/m/a/request?token=${status}`)).toBe(true);
    }
    expect(net.mine).toHaveBeenCalledOnce();
  });
});
