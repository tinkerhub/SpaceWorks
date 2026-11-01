import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanUploadSession, held, http, json, release, resetUploadSession } from "../../../../test/staffUploadHarness";
import type { MachineServiceRequest } from "../../../../generated/api";
import { attachment, detailedJob, expandDetails, mountDetails } from "./serviceDetailsTestHarness";

beforeEach(() => { resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => cleanUploadSession());

describe("service project details", () => {
  it("shows requester, job ID, brief, assigned machine, source and filenames without reading a file", () => {
    const net = http(() => json({ url: "https://private.test/file" }));
    mountDetails();
    expect(screen.getByText("Job #4 · Ada · Assigned press")).toBeVisible();
    expect(screen.queryByText(/Legacy bucket/)).not.toBeInTheDocument();
    expandDetails();
    expect(screen.getByText(/Cut two tabs/)).toHaveTextContent("Keep the offcuts.");
    expect(screen.getByText(attachment.original_filename)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open project source" })).toHaveAttribute("href", "https://design.test/project");
    expect(screen.getByRole("link", { name: "Open project source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "Open project source" })).toHaveAttribute("target", "_blank");
    expect(net.calls).toEqual([]);
  });

  it.each([
    { requester_name: "", requester: { id: 1, display: "Display maker", username: "maker" }, expected: "Display maker" },
    { requester_name: "", requester: { id: 1, display: "", username: "maker" }, expected: "maker" },
    { requester_name: "", requester: null, expected: "Unknown requester" },
  ])("uses the safe requester fallback $expected and legacy machine", ({ expected, ...requester }) => {
    // Legacy/unassigned HTTP rows can contain null despite the generated schema.
    mountDetails({ ...detailedJob, ...requester, assigned_machine: null } as unknown as MachineServiceRequest);
    expect(screen.getByText(`Job #4 · ${expected} · Legacy bucket`)).toBeVisible();
  });

  it("shows an unassigned job and renders descriptions and filenames as plain escaped text", () => {
    const markup = '<img src=x onerror="alert(1)"><script>attack()</script>';
    const view = mountDetails({ ...detailedJob, machine: null, assigned_machine: null,
      description: markup, files: [{ ...attachment, original_filename: `${markup}.stl` }] } as unknown as MachineServiceRequest);
    expect(screen.getByText("Job #4 · Ada · Machine not assigned")).toBeVisible();
    expandDetails();
    expect(screen.getByText(markup)).toBeVisible();
    expect(screen.getByText(`${markup}.stl`)).toBeVisible();
    expect(view.container.querySelector("img,script")).toBeNull();
  });

  it.each(["javascript:alert(1)", "data:text/html,attack", "ftp://design.test/file", "not a URL"])("refuses an unsafe project source %s", (source_link) => {
    mountDetails({ ...detailedJob, source_link });
    expandDetails();
    expect(screen.queryByRole("link", { name: "Open project source" })).not.toBeInTheDocument();
    expect(screen.getByText(/only HTTP\(S\) links can be opened/)).toBeVisible();
  });
});

describe("on-demand service file URLs", () => {
  it.each(["https://private.test/file?signature=secret", "http://private.test/file?signature=secret"])("offers a current %s as a safe link and leaves no signed URL in cache or persistence", async (url) => {
    const net = http(() => json({ url }));
    const view = mountDetails();
    expandDetails();
    expect(net.calls).toHaveLength(0);
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    expect(window.open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    const link = await screen.findByRole("link", { name: "Open fixture.stl" });
    expect(link).toBeVisible();
    expect(link).toHaveAttribute("href", url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/^File link ready\./)).toHaveTextContent("File link ready. Select Open file to view it.");
    expect(window.open).not.toHaveBeenCalled();
    expect(net.calls.map((call) => [call.method, call.path])).toEqual([["GET", "/admin/machine-service/files/81/url"]]);
    const cache = JSON.stringify({ queries: view.client.getQueryCache().getAll().map((query) => query.state),
      mutations: view.client.getMutationCache().getAll().map((mutation) => mutation.state) });
    expect(cache).not.toContain(url);
    for (const storage of [localStorage, sessionStorage]) {
      expect(JSON.stringify(Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index)!)))).not.toContain(url);
    }
    expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeEnabled();
  });

  it("keeps a delayed URL read popup-free and lets a user click the ready anchor even when popups are blocked", async () => {
    const response = held<Response>();
    const url = "https://private.test/delayed?signature=secret";
    const net = http(() => response.promise);
    mountDetails(); expandDetails();
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    await waitFor(() => expect(net.calls).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
    expect(window.open).not.toHaveBeenCalled(); // Includes pre-opening an intermediate blank window.
    await release(response, json({ url }));
    const link = await screen.findByRole("link", { name: "Open fixture.stl" });
    expect(link.tagName).toBe("A");
    expect(link).toBeVisible();
    expect(link).toHaveAttribute("href", url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/^File link ready\./)).toHaveTextContent("File link ready.");
    expect(window.open).not.toHaveBeenCalled();
    // Dispatch through the real DOM handler: the current owner must allow native link navigation.
    expect(fireEvent.click(link)).toBe(true);
    expect(window.open).not.toHaveBeenCalled();
    expect(net.calls).toHaveLength(1);
  });

  it.each(["javascript:alert(1)", "data:text/html,attack", "ftp://private.test/file", "%%%bad URL"])("refuses an unsafe returned file URL %s", async (url) => {
    http(() => json({ url }));
    mountDetails(); expandDetails();
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    expect(await screen.findByText("The file link is unavailable. Try opening it again.")).toBeVisible();
    expect(window.open).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
  });

  it("keeps filenames after storage failure and retries the real URL read", async () => {
    let failed = true;
    const net = http(() => failed ? json({ detail: "Private storage unavailable" }, 503) : json({ url: "https://private.test/retried" }));
    mountDetails(); expandDetails();
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    expect(await screen.findByText("Private storage unavailable")).toBeVisible();
    expect(screen.getByText("Use Get file link to retry.")).toBeVisible();
    expect(window.open).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    expect(await screen.findByRole("link", { name: "Open fixture.stl" })).toHaveAttribute("href", "https://private.test/retried");
    expect(window.open).not.toHaveBeenCalled();
    expect(screen.getByText(/^File link ready\./)).toHaveTextContent("File link ready.");
    expect(net.calls).toHaveLength(2);
    expect(screen.queryByText("Private storage unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText("Use Get file link to retry.")).not.toBeInTheDocument();
  });
});
