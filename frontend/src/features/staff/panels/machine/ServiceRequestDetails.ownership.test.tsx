import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanUploadSession, held, http, json, login, release, resetUploadSession } from "../../../../test/staffUploadHarness";
import { attachment, detailedJob, detailsTree, expandDetails, mountDetails } from "./serviceDetailsTestHarness";

beforeEach(() => { resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => cleanUploadSession());

describe.each([false, true])("deferred file URL failure=%s", (fail) => {
  it.each(["type", "makerspace", "request", "files", "session", "unmount"] as const)("cannot publish after %s leaves and returns", async (change) => {
    const old = held<Response>(); const replacement = held<Response>();
    let reads = 0;
    const net = http(() => ++reads === 1 ? old.promise : replacement.promise);
    const view = mountDetails(); expandDetails();
    fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
    await waitFor(() => expect(net.calls).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeDisabled();
    if (change === "type") {
      fireEvent.click(screen.getByRole("button", { name: "Other type" }));
      fireEvent.click(screen.getByRole("button", { name: "Original type" }));
    } else if (change === "unmount") {
      view.unmount();
    } else if (change === "session") {
      login("B");
      view.rerender(detailsTree());
    } else {
      const request = change === "request" ? { ...detailedJob, id: 5 }
        : change === "files" ? { ...detailedJob, files: [{ ...attachment, id: 82 }] } : detailedJob;
      view.rerender(detailsTree(request, change === "makerspace" ? 2 : 1));
      view.rerender(detailsTree()); // A→B→A must revoke A's original read lifetime too.
    }
    if (change !== "unmount") {
      expandDetails();
      expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeEnabled();
      fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
      await waitFor(() => expect(net.calls).toHaveLength(2));
    }
    await release(old, fail ? json({ detail: "Obsolete file read failed" }, 503)
      : json({ url: "https://private.test/obsolete" }));
    expect(window.open).not.toHaveBeenCalled();
    expect(screen.queryByText(/Obsolete file read failed/)).not.toBeInTheDocument();
    expect(view.container.innerHTML).not.toContain("https://private.test/obsolete");
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
    if (change !== "unmount") {
      // An old finally must not release the replacement read's pending state.
      expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeDisabled();
      await release(replacement, json({ url: "https://private.test/current" }));
      const link = await screen.findByRole("link", { name: "Open fixture.stl" });
      expect(link).toHaveAttribute("href", "https://private.test/current");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getAllByRole("link", { name: "Open fixture.stl" })).toHaveLength(1);
      expect(view.container.innerHTML).not.toContain("https://private.test/obsolete");
      expect(screen.getByText(/^File link ready\./)).toHaveTextContent("File link ready.");
      expect(window.open).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeEnabled();
    }
  });
});

it.each([false, true])("session replacement without a React render suppresses late file publication, failure=%s", async (fail) => {
  const response = held<Response>();
  const net = http(() => response.promise);
  const view = mountDetails(); expandDetails();
  fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
  await waitFor(() => expect(net.calls).toHaveLength(1));
  login("B"); // The guard must read the real auth epoch even before React renders again.
  await release(response, fail ? json({ detail: "Old session storage failure" }, 503)
    : json({ url: "https://private.test/old-session" }));
  expect(window.open).not.toHaveBeenCalled();
  expect(screen.queryByText(/Old session storage failure/)).not.toBeInTheDocument();
  expect(view.container.innerHTML).not.toContain("https://private.test/old-session");
  expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
  expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
});

it("prevents a ready link click after session replacement before React renders", async () => {
  const net = http(() => json({ url: "https://private.test/old-session" }));
  const view = mountDetails(); expandDetails();
  fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
  const link = await screen.findByRole("link", { name: "Open fixture.stl" });
  login("B"); // Keep the old DOM in place to exercise the click-time auth check.
  expect(link).toBeInTheDocument();
  const click = new MouseEvent("click", { bubbles: true, cancelable: true });
  expect(fireEvent(link, click)).toBe(false);
  expect(click.defaultPrevented).toBe(true);
  expect(window.open).not.toHaveBeenCalled();
  expect(net.calls).toHaveLength(1);
  view.rerender(detailsTree());
  expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
  expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
  expect(view.container.innerHTML).not.toContain("https://private.test/old-session");
});

it.each(["type", "makerspace", "request", "files", "session", "unmount"] as const)("revokes a ready link when %s changes, including a return visit", async (change) => {
  const url = "https://private.test/previous-visit";
  const net = http(() => json({ url }));
  const view = mountDetails(); expandDetails();
  fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
  expect(await screen.findByRole("link", { name: "Open fixture.stl" })).toHaveAttribute("href", url);
  const assertRevoked = () => {
    expect(view.container.innerHTML).not.toContain(url);
    expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
  };
  if (change === "type") {
    fireEvent.click(screen.getByRole("button", { name: "Other type" }));
    assertRevoked();
    fireEvent.click(screen.getByRole("button", { name: "Original type" }));
  } else if (change === "unmount") {
    view.unmount();
  } else if (change === "session") {
    login("B");
    view.rerender(detailsTree());
    assertRevoked();
    login("A");
    view.rerender(detailsTree());
  } else {
    const request = change === "request" ? { ...detailedJob, id: 5 }
      : change === "files" ? { ...detailedJob, files: [{ ...attachment, id: 82 }] } : detailedJob;
    view.rerender(detailsTree(request, change === "makerspace" ? 2 : 1));
    assertRevoked();
    view.rerender(detailsTree());
  }
  assertRevoked();
  expect(net.calls).toHaveLength(1); // Returning must not silently fetch or restore a signed URL.
  expect(window.open).not.toHaveBeenCalled();
});

it("revokes the previous ready link as soon as another attachment read starts", async () => {
  const next = held<Response>();
  const net = http((call) => call.path.endsWith("/81/url") ? json({ url: "https://private.test/first" }) : next.promise);
  const view = mountDetails({ ...detailedJob, files: [attachment, { ...attachment, id: 82, original_filename: "second.stl" }] });
  expandDetails();
  fireEvent.click(screen.getByRole("button", { name: "Get link for fixture.stl" }));
  expect(await screen.findByRole("link", { name: "Open fixture.stl" })).toHaveAttribute("href", "https://private.test/first");
  fireEvent.click(screen.getByRole("button", { name: "Get link for second.stl" }));
  await waitFor(() => expect(net.calls).toHaveLength(2));
  expect(view.container.innerHTML).not.toContain("https://private.test/first");
  expect(screen.queryByRole("link", { name: /^Open .*\.stl$/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/^File link ready\./)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Get link for fixture.stl" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Get link for second.stl" })).toBeDisabled();
  await release(next, json({ url: "https://private.test/second" }));
  expect(await screen.findByRole("link", { name: "Open second.stl" })).toHaveAttribute("href", "https://private.test/second");
  expect(screen.queryByRole("link", { name: "Open fixture.stl" })).not.toBeInTheDocument();
  expect(view.container.innerHTML).not.toContain("https://private.test/first");
  expect(screen.getByText(/^File link ready\./)).toHaveTextContent("File link ready.");
  expect(window.open).not.toHaveBeenCalled();
});
