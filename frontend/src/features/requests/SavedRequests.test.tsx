import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getSessionGeneration } from "../../lib/apiSession";
import { hardware, json, machine, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { MyRequestsPage } from "./MyRequestsPage";
import { revealRequestCapabilities, saveRequestCapability } from "./requestCapabilities";
import { savedRequestKey } from "./requestsApi";

let net: ReturnType<typeof requestHistoryNetwork>;
beforeEach(() => { net = requestHistoryNetwork(); });
afterEach(() => { net.dispose(); vi.restoreAllMocks(); });
const content = <Routes><Route path="/m/:slug/my-requests" element={<MyRequestsPage />} /><Route path="/elsewhere" element={<p>Elsewhere</p>} /></Routes>;
const reveal = () => fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
const seed = (count = 7) => {
  localStorage.setItem("spaceworks.requests.a", JSON.stringify(Array.from({ length: count }, (_, i) => ({
    kind: "hardware", token: `saved-${i}`, saved_at: 100 - i,
  }))));
};

describe("private browser history requires explicit visit consent", () => {
  it("has no private HTTP, title or href before reveal, then fetches only six per page with bounded navigation", async () => {
    seed(); net.mount(content);
    await screen.findByRole("button", { name: "Show requests saved on this browser" });
    expect(screen.getByText(/shared browser/)).toBeVisible();
    expect(screen.getByText(/A check-in name does not prove ownership/)).toBeVisible();
    expect(net.status).not.toHaveBeenCalled(); expect(net.mine).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Open private status link" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Tool saved-/)).not.toBeInTheDocument();
    reveal();
    await screen.findByText("Tool saved-5");
    expect(net.status).toHaveBeenCalledTimes(6);
    expect(screen.getAllByRole("link", { name: "Open private status link" })).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByText(/7 requests · Page 1 · Up to 6/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Tool saved-6");
    expect(net.status).toHaveBeenCalledTimes(7);
    expect(screen.queryByText("Tool saved-0")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open private status link" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByText("Tool saved-0");
    expect(net.status).toHaveBeenCalledTimes(7);
    await act(async () => { window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("online")); });
    expect(net.status).toHaveBeenCalledTimes(7);
    for (const [url, init] of net.status.mock.calls) {
      expect(url.pathname).toMatch(/\/public\/requests\/saved-\d\/status$/);
      expect(init?.method ?? "GET").toBe("GET");
    }
    expect(net.other).not.toHaveBeenCalled();
  });

  it("hides after Hide, a new route visit, tenant A→B→A and unmount, even with cached private results", async () => {
    seed(1); saveRequestCapability("b", "machine", "private-b");
    const view = net.mount(content);
    reveal(); await screen.findByText("Tool saved-0");
    fireEvent.click(screen.getByRole("button", { name: "Hide saved requests" }));
    expect(screen.queryByText("Tool saved-0")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open private status link" })).not.toBeInTheDocument();
    reveal(); await screen.findByText("Tool saved-0");
    view.navigate("/m/a/my-requests?visit=2");
    expect(screen.queryByText("Tool saved-0")).not.toBeInTheDocument();
    reveal(); await screen.findByText("Tool saved-0");
    view.navigate("/m/b/my-requests");
    expect(screen.queryByText("Tool saved-0")).not.toBeInTheDocument();
    expect(screen.queryByText("Project private-b")).not.toBeInTheDocument();
    view.navigate("/m/a/my-requests");
    expect(screen.queryByRole("link", { name: "Open private status link" })).not.toBeInTheDocument();
    expect(net.status).toHaveBeenCalledOnce();
    reveal(); await screen.findByText("Tool saved-0");
    view.unmount(); net.mount(content, "/m/a/my-requests", view.client);
    expect(screen.queryByText("Tool saved-0")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
  });

  it("imports legacy links only on reveal and keeps a failing row independent from its successful neighbor", async () => {
    localStorage.setItem("tinkerspace.printStatus.a", "old printer / &");
    saveRequestCapability("a", "hardware", "good");
    let failed = true;
    net.status.mockImplementation(async (url) => url.pathname.includes("machine-service")
      ? failed ? json({ detail: "Unavailable" }, 503) : json(machine("old printer / &"))
      : json(hardware("good")));
    net.mount(content);
    expect(net.status).not.toHaveBeenCalled();
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBe("old printer / &");
    reveal();
    await screen.findByText("Tool good");
    expect(await screen.findByText("Requests could not be loaded. Please try again.")).toBeVisible();
    expect(net.status).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("link", { name: "Open private status link" }).map((link) => link.getAttribute("href")))
      .toContain("/m/a/machine-service?token=old%20printer%20%2F%20%26");
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBeNull();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry status" }));
    expect(await screen.findByRole("heading", { name: "Project old printer / &" })).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry status" })).not.toBeInTheDocument());
    expect(net.status).toHaveBeenCalledTimes(3);
  });

  it("Forget one removes exact capability caches and legacy references, preserves other scopes and never cancels", async () => {
    saveRequestCapability("a", "machine", "forget-me");
    const view = net.mount(content);
    const generation = getSessionGeneration();
    const removed = [savedRequestKey("a", generation, "machine", "forget-me"),
      ["public-service-status", "a", "forget-me"], ["public-service-status", "a", "forget-me", generation]];
    const kept = [savedRequestKey("b", generation, "machine", "forget-me"),
      savedRequestKey("a", generation + 1, "machine", "forget-me"), ["my-requests", "a", generation, "machine", 1]];
    [...removed.slice(1), ...kept].forEach((key) => view.client.setQueryData(key, { keep: true }));
    reveal(); await screen.findByText("Project forget-me");
    // A compatibility writer may have repeated the last-token key after reveal.
    localStorage.setItem("tinkerspace.serviceStatus.a", "forget-me");
    fireEvent.click(screen.getByRole("button", { name: "Forget this link" }));
    expect(await screen.findByText("No saved links for the available request types")).toBeVisible();
    removed.forEach((key) => expect(view.client.getQueryData(key)).toBeUndefined());
    kept.forEach((key) => expect(view.client.getQueryData(key)).toEqual({ keep: true }));
    expect(revealRequestCapabilities("a").records).toEqual([]);
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
    expect(net.other).not.toHaveBeenCalled();
    expect(net.fetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("Forget all clears both kinds and their private caches while preserving another tenant", async () => {
    saveRequestCapability("a", "hardware", "tool"); saveRequestCapability("a", "machine", "job");
    saveRequestCapability("b", "hardware", "elsewhere");
    const view = net.mount(content); reveal();
    await screen.findByText("Tool tool"); await screen.findByText("Project job");
    fireEvent.click(screen.getByRole("button", { name: "Forget all saved links" }));
    expect(await screen.findByText("No saved links for the available request types")).toBeVisible();
    expect(view.client.getQueryCache().findAll({ queryKey: ["saved-request-status", "a"] })).toHaveLength(0);
    expect(revealRequestCapabilities("a").records).toEqual([]);
    expect(revealRequestCapabilities("b").records.map((row) => row.token)).toEqual(["elsewhere"]);
    expect(net.other).not.toHaveBeenCalled();
  });

  it("warns truthfully and retains the visible link if forgetting cannot be verified", async () => {
    seed(1); net.mount(content); reveal(); await screen.findByText("Tool saved-0");
    const set = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key === "spaceworks.requests.a") throw new Error("Quota");
      set.call(this, key, value);
    });
    const section = within(screen.getByRole("region", { name: "Saved on this browser" }));
    fireEvent.click(section.getByRole("button", { name: "Forget this link" }));
    expect(await section.findByText(/could not verify that the link was forgotten/)).toBeVisible();
    expect(section.getByRole("link", { name: "Open private status link" })).toBeVisible();
    expect(section.queryByText("No saved links for the available request types")).not.toBeInTheDocument();
    expect(revealRequestCapabilities("a").records.map((row) => row.token)).toEqual(["saved-0"]);
  });
});
