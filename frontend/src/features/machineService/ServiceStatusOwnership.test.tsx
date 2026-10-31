import { useLayoutEffect } from "react";
import { act, screen, waitFor } from "@testing-library/react";
import { useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { API_V1_URL, accessToken, deferred, json, mountServiceRoute, serviceNetwork, serviceStatus,
  submit, title, type ServiceNetwork } from "../../test/serviceOwnershipHarness";
import { revealRequestCapabilities } from "../requests/requestCapabilities";
import { ServiceRequestForm } from "./ServiceRequestForm";
import { genericType } from "./serviceTestFixtures";
import { ServiceStatusPanel, useServiceStatus } from "./ServiceStatusPanel";

type Tracker = ReturnType<typeof useServiceStatus>;
let net: ServiceNetwork;
let visits: Tracker[];
let publicationFrames: string[];
beforeEach(() => {
  net = serviceNetwork(); visits = []; publicationFrames = [];
  net.status.mockImplementation(async (url) => {
    const segments = new URL(url, "http://localhost").pathname.split("/");
    const token = decodeURIComponent(segments[segments.length - 2]);
    return json({ ...serviceStatus, public_token: token, title: `Status ${token}` });
  });
});
afterEach(() => { net.dispose(); vi.restoreAllMocks(); });
function TrackerProbe({ person = "Ada", legacy = false }: { person?: string; legacy?: boolean }) {
  const { slug = "" } = useParams();
  const tracker = useServiceStatus(slug, true, legacy, person);
  useLayoutEffect(() => { visits.push(tracker); publicationFrames.push(document.body.textContent ?? ""); });
  return <><ServiceRequestForm slug={slug} type={genericType} identity={{ name: person, checkin_mid: person === "Ada" ? 1 : 2 }}
    identityReady onPendingChange={() => {}} onSuccess={tracker.onSuccess} />
    <ServiceStatusPanel tracker={tracker} statusPath={`/m/${slug}/machine-service`} /></>;
}
const latest = () => visits[visits.length - 1];
const link = () => screen.getByRole("link", { name: "Your private status link" });
async function createCurrent(token: string) {
  net.create.mockResolvedValueOnce(json({ public_token: token, status: "pending" }));
  title(`Project for ${token}`); submit();
  await screen.findByText(`Status ${token}`);
  await waitFor(() => expect(screen.getByLabelText("Title")).toBeEnabled());
  await waitFor(() => expect(latest().query.isFetching).toBe(false));
}

describe("service tracker capabilities and ephemeral visit ownership", () => {
  it("uses an explicit encoded URL capability ahead of a saved token", async () => {
    localStorage.setItem("tinkerspace.serviceStatus.a", "saved-a");
    mountServiceRoute(net, <TrackerProbe />, "/m/a/service?token=url%2Fsecret%20%26");
    await screen.findByText("Status url/secret &");
    expect(net.status.mock.calls[0][0]).toBe(`${API_V1_URL}/public/machine-service/requests/url%2Fsecret%20%26/status`);
    expect(link()).toHaveAttribute("href", "/m/a/machine-service?token=url%2Fsecret%20%26");
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("saved-a");
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(latest().token).toBe("url/secret &");
  });

  it("keeps legacy printer links hidden until explicit reveal and an explicit private URL", async () => {
    localStorage.setItem("tinkerspace.printStatus.a", "legacy-printer");
    const view = mountServiceRoute(net, <TrackerProbe legacy />, "/m/a/service");
    expect(latest().token).toBe("");
    expect(net.status).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Your private status link" })).not.toBeInTheDocument();
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBe("legacy-printer");
    expect(revealRequestCapabilities("a")).toEqual({ saved: true, records: [
      { kind: "machine", token: "legacy-printer", saved_at: expect.any(Number) },
    ] });
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBeNull();
    expect(latest().token).toBe("");
    view.navigate("/m/a/service?token=legacy-printer");
    await screen.findByText("Status legacy-printer");
    expect(link()).toHaveAttribute("href", "/m/a/machine-service?token=legacy-printer");
    localStorage.setItem("tinkerspace.serviceStatus.a", "newer-service");
    view.navigate("/m/b/service"); view.navigate("/m/a/service");
    expect(latest().token).toBe("");
    expect(screen.queryByRole("link", { name: "Your private status link" })).not.toBeInTheDocument();
    expect(net.status).toHaveBeenCalledOnce();
  });

  it("masks completion before paint on A→B→A and fences stale success/retry/storage publication", async () => {
    localStorage.setItem("tinkerspace.serviceStatus.a", "saved-a");
    localStorage.setItem("tinkerspace.serviceStatus.b", "saved-b");
    const writes = vi.spyOn(Storage.prototype, "setItem");
    const view = mountServiceRoute(net, <TrackerProbe />, "/m/a/service");
    expect(latest().token).toBe("");
    expect(net.status).not.toHaveBeenCalled();
    const oldA = latest();
    await createCurrent("accepted-a");
    expect(screen.getByText("Request submitted")).toBeVisible();
    await screen.findByText("Status accepted-a");
    view.frames.length = 0;
    view.navigate("/m/b/service");
    expect(latest().token).toBe("");
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(screen.queryByText("Status accepted-a")).not.toBeInTheDocument();
    const b = latest();
    await createCurrent("accepted-b");
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("accepted-b");
    await screen.findByText("Status accepted-b");
    view.navigate("/m/a/service");
    expect(latest().token).toBe("");
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(screen.queryByText("Status accepted-a")).not.toBeInTheDocument();
    expect(screen.queryByText("Status accepted-b")).not.toBeInTheDocument();
    const requests = net.status.mock.calls.length;
    writes.mockClear();
    await act(async () => { oldA.onSuccess("obsolete-a"); oldA.retry(); b.onSuccess("obsolete-b"); b.retry(); });
    expect(net.status).toHaveBeenCalledTimes(requests);
    expect(latest().token).toBe("");
    expect(writes).not.toHaveBeenCalled();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("accepted-a");
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("accepted-b");
    expect(view.frames.every((frame) => !frame.text.includes("Request submitted") || frame.path === "/m/b/service"))
      .toBe(true);
    for (const frame of view.frames) {
      expect(frame.text).not.toContain(frame.path === "/m/b/service" ? "Status accepted-a" : "Status accepted-b");
    }
  });

  it("clears a person's ephemeral completion without erasing the saved capability or reviving old callbacks", async () => {
    const view = mountServiceRoute(net, <TrackerProbe />, "/m/a/service");
    const ada = latest();
    await createCurrent("same-browser-token");
    await screen.findByText("Status same-browser-token");
    expect(screen.getByText("Request submitted")).toBeVisible();
    view.frames.length = 0;
    view.redraw(<TrackerProbe person="Bea" />);
    expect(latest().token).toBe("");
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(view.frames.length).toBeGreaterThan(0);
    expect(view.frames.every((frame) => !frame.text.includes("Request submitted"))).toBe(true);
    act(() => ada.onSuccess("obsolete-person-token"));
    expect(latest().token).toBe("");
    view.redraw(<TrackerProbe person="Ada" />);
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("same-browser-token");
  });

  it("keeps the changed URL visit current despite old completion and retry closures", async () => {
    net.status.mockResolvedValueOnce(json({ detail: "Old token unavailable" }, 503));
    const view = mountServiceRoute(net, <TrackerProbe />, "/m/a/service?token=old-url");
    await screen.findByText("Old token unavailable");
    const old = latest();
    view.frames.length = 0;
    view.navigate("/m/a/service?token=new-url");
    expect(latest().token).toBe("new-url");
    expect(screen.queryByText("Old token unavailable")).not.toBeInTheDocument();
    expect(view.frames.length).toBeGreaterThan(0);
    for (const frame of view.frames) {
      expect(frame.text).not.toContain("Old token unavailable");
      expect(frame.links).toContain("/m/a/machine-service?token=new-url");
      expect(frame.links).not.toContain("/m/a/machine-service?token=old-url");
    }
    await screen.findByText("Status new-url");
    const requests = net.status.mock.calls.length;
    await act(async () => { old.retry(); old.onSuccess("obsolete-url-result"); });
    expect(net.status).toHaveBeenCalledTimes(requests);
    expect(link()).toHaveAttribute("href", "/m/a/machine-service?token=new-url");
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    await createCurrent("current-result");
    expect(screen.getByText("Request submitted")).toBeVisible();
    expect(link()).toHaveAttribute("href", "/m/a/machine-service?token=current-result");
  });

  it("masks an auth visit's banner before paint while preserving capability compatibility across actors", async () => {
    const view = mountServiceRoute(net, <TrackerProbe />, "/m/a/service?token=explicit-capability");
    await screen.findByText("Status explicit-capability");
    const old = latest();
    await createCurrent("member-one-result");
    expect(screen.getByText("Request submitted")).toBeVisible();
    publicationFrames.length = 0;
    act(() => { setAccessToken(accessToken("actor-two", { user_id: 2 })); });
    expect(latest().token).toBe("explicit-capability");
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(publicationFrames.length).toBeGreaterThan(0);
    expect(publicationFrames.every((text) => !text.includes("Request submitted"))).toBe(true);
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("member-one-result");
    act(() => old.onSuccess("stale-account-result"));
    expect(latest().token).toBe("explicit-capability");
    expect(link()).toHaveAttribute("href", "/m/a/machine-service?token=explicit-capability");
    view.navigate("/m/a/service");
    expect(latest().token).toBe("");
    expect(screen.queryByRole("link", { name: "Your private status link" })).not.toBeInTheDocument();
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
  });

  it("prevents held obsolete completion/persistence and retry work after departure or unmount", async () => {
    const view = mountServiceRoute(net, <TrackerProbe />, "/m/a/service?token=mounted-token");
    await screen.findByText("Status mounted-token");
    await createCurrent("mounted-token");
    const old = latest();
    const heldA = deferred<string>();
    const completionA = heldA.promise.then((token) => old.onSuccess(token));
    const writes = vi.spyOn(Storage.prototype, "setItem");
    // Completion is released only after A departed. A valid earlier completion may persist.
    view.navigate("/m/b/service?token=b-url");
    await screen.findByText("Status b-url");
    await createCurrent("b-url");
    writes.mockClear();
    await act(async () => { heldA.resolve("late-a"); await completionA; old.retry(); });
    expect(latest().token).toBe("b-url");
    expect(writes).not.toHaveBeenCalled();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("mounted-token");
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("b-url");
    const b = latest();
    const heldB = deferred<string>();
    const completionB = heldB.promise.then((token) => b.onSuccess(token));
    view.unmount(); writes.mockClear();
    const requests = net.status.mock.calls.length;
    await act(async () => {
      heldB.resolve("after-unmount-b"); await completionB;
      old.onSuccess("after-unmount-a"); old.retry(); b.retry();
    });
    expect(writes).not.toHaveBeenCalled();
    expect(net.status).toHaveBeenCalledTimes(requests);
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("mounted-token");
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("b-url");
  });
});
