import { fireEvent, screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, json, machine, page, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { MyRequestsPage } from "../requests/MyRequestsPage";
import { saveRequestCapability } from "../requests/requestCapabilities";

let net: ReturnType<typeof requestHistoryNetwork>;
afterEach(() => net.dispose());

describe("My requests reuses machine service status semantics", () => {
  it("shows all lifecycle states, Ready to collect for completed and terminal failure callouts", async () => {
    net = requestHistoryNetwork({ accounts: true, modules: ["machine_service"] });
    setAccessToken(accessToken("status-account"));
    const states = ["pending", "accepted", "in_progress", "completed", "collected", "failed", "rejected"];
    net.mine.mockResolvedValueOnce(json(page(states.map((status) => machine(status, status)))));
    net.mount(<Routes><Route path="/m/:slug/my-requests" element={<MyRequestsPage />} /></Routes>);
    await screen.findByRole("heading", { name: "Project completed" });
    const section = screen.getByRole("region", { name: "Machine service requests" });
    const cards = within(section).getAllByRole("link", { name: "Open private status link" }).map((link) => link.parentElement!);
    expect(cards).toHaveLength(7);
    states.forEach((status, index) => {
      const card = within(cards[index]);
      expect(card.getAllByRole("heading", { name: `Project ${status}` })).toHaveLength(1);
      expect(card.getAllByText(/^Created /)).toHaveLength(1);
      expect(card.getByRole("link")).toHaveAttribute("href", `/m/a/machine-service?token=${status}`);
      if (status === "failed" || status === "rejected") {
        expect(card.getByRole("status")).toHaveTextContent(`Project ${status} is ${status}.`);
        expect(card.queryByRole("list")).not.toBeInTheDocument();
      } else {
        const current = cards[index].querySelector('[aria-current="step"]');
        expect(current).toHaveTextContent(status === "completed" ? "Ready to collect" : status === "pending" ? "Requested"
          : status === "in_progress" ? "In progress" : status === "accepted" ? "Accepted" : "Collected");
      }
    });
    expect(net.mine).toHaveBeenCalledOnce();
  });

  it("uses those same status semantics for revealed browser links across the six-row page boundary", async () => {
    net = requestHistoryNetwork({ modules: ["machine_service"] });
    const states = ["pending", "accepted", "in_progress", "completed", "collected", "failed", "rejected"];
    states.forEach((status) => saveRequestCapability("a", "machine", status));
    // Explicit timestamps fix page order without a fake clock or any polling delay.
    localStorage.setItem("spaceworks.requests.a", JSON.stringify(states.map((token, index) => ({ kind: "machine", token, saved_at: 100 - index }))));
    localStorage.removeItem("tinkerspace.serviceStatus.a");
    net.status.mockImplementation(async (url) => {
      const parts = url.pathname.split("/"); const status = parts[parts.length - 2];
      return json(machine(status, status));
    });
    net.mount(<Routes><Route path="/m/:slug/my-requests" element={<MyRequestsPage />} /></Routes>);
    expect(net.status).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
    await screen.findByRole("heading", { name: "Project failed" });
    expect(screen.getByText("Project failed is failed.")).toBeVisible();
    for (const status of states.slice(0, 6)) expect(screen.getByRole("heading", { name: `Project ${status}` })).toBeVisible();
    const ready = screen.getByRole("heading", { name: "Project completed" }).parentElement?.parentElement;
    expect(ready?.querySelector('[aria-current="step"]')).toHaveTextContent("Ready to collect");
    expect(net.status).toHaveBeenCalledTimes(6);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Project rejected is rejected.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Project completed" })).not.toBeInTheDocument();
    expect(net.status).toHaveBeenCalledTimes(7);
    expect(net.mine).not.toHaveBeenCalled();
  });
});
