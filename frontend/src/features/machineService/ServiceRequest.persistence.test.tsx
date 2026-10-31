import { useState } from "react";
import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, deferred, genericType, json, mountServiceForm, mountServiceRoute, personB,
  serviceNetwork, submit, title, type ServiceNetwork } from "../../test/serviceOwnershipHarness";
import { revealRequestCapabilities } from "../requests/requestCapabilities";
import { PublicMachineServicePage } from "./PublicMachineServicePage";
import { ServiceRequestForm } from "./ServiceRequestForm";

let net: ServiceNetwork;
beforeEach(() => { net = serviceNetwork(); });
afterEach(() => { net.dispose(); vi.restoreAllMocks(); });

describe("actual service form persistence and shared-browser privacy", () => {
  it("saves two actual successful references before the completion callback unmounts each form", async () => {
    const outcomes: unknown[][] = [];
    function FormOwner() {
      const [visit, setVisit] = useState(0), [visible, setVisible] = useState(true);
      return <><button onClick={() => { setVisit((v) => v + 1); setVisible(true); }}>Next project</button>
        {visible ? <ServiceRequestForm key={visit} slug="a" type={genericType} identity={{}} identityReady
          onPendingChange={() => {}} onSuccess={(...args) => {
            expect(revealRequestCapabilities("a").records.map((row) => row.token)).toContain(`service-${visit + 1}`);
            outcomes.push(args); setVisible(false);
          }} /> : null}</>;
    }
    net.create.mockResolvedValueOnce(json({ public_token: "service-1", status: "pending" }))
      .mockResolvedValueOnce(json({ public_token: "service-2", status: "pending" }));
    const view = mountServiceRoute(net, <FormOwner />);
    title(); submit(); await waitFor(() => expect(outcomes).toHaveLength(1));
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next project" })); title(); submit();
    await waitFor(() => expect(outcomes).toHaveLength(2));
    for (let i = 0; i < 2; i++) expect(outcomes[i]).toEqual([`service-${i + 1}`,
      { saved: true, records: expect.arrayContaining([{ kind: "machine", token: `service-${i + 1}`, saved_at: expect.any(Number) }]) }]);
    expect(revealRequestCapabilities("a").records.map((row) => row.token).sort()).toEqual(["service-1", "service-2"]);
    view.unmount();
    expect(revealRequestCapabilities("a").records).toHaveLength(2);
    expect(net.create).toHaveBeenCalledTimes(2);
  });

  it("keeps a committed current receipt and private link when registry storage throws", async () => {
    const set = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key.startsWith("spaceworks.requests.")) throw new Error("Quota");
      set.call(this, key, value);
    });
    mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText("Title"); title(); submit();
    expect(await screen.findByText("Request submitted")).toBeVisible();
    expect(screen.getByRole("link", { name: "Your private status link" })).toHaveAttribute("href", "/m/a/machine-service?token=current-token");
    expect(screen.getByText(/could not verify the saved links/)).toBeVisible();
    expect(screen.queryByText("Service request wasn't submitted")).not.toBeInTheDocument();
    expect(await screen.findByText("Project enclosure")).toBeVisible();
    expect(net.create).toHaveBeenCalledOnce();
  });

  it("never fetches an old browser service on blank or newly confirmed check-in identity; current success is immediate", async () => {
    net.bootstraps.get("a")!.makerspace.request_access = "checked_in";
    localStorage.setItem("tinkerspace.serviceStatus.a", "other-person-secret");
    localStorage.setItem("tinkerspace.printStatus.a", "old-printer-secret");
    mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText(/Your name, as it appears/);
    expect(net.status).not.toHaveBeenCalled();
    expect(screen.queryByText("Project enclosure")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Your private status link" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View saved requests" })).toHaveAttribute("href", "/m/a/my-requests");
    fireEvent.change(screen.getByLabelText(/Your name, as it appears/), { target: { value: "Ada" } });
    fireEvent.click(screen.getByRole("button", { name: "Find me" }));
    await screen.findByRole("button", { name: "Not you?" });
    expect(net.status).not.toHaveBeenCalled();
    title("Current check-in project"); submit();
    await screen.findByText("Request submitted"); await screen.findByText("Project enclosure");
    expect(net.status).toHaveBeenCalledOnce();
    expect(net.status.mock.calls[0][0]).toContain("/current-token/status");
    fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
    expect(screen.queryByRole("link", { name: "Your private status link" })).not.toBeInTheDocument();
    expect(screen.queryByText("Project enclosure")).not.toBeInTheDocument();
    net.lookup.mockResolvedValueOnce(json([personB]));
    fireEvent.change(screen.getByLabelText(/Your name, as it appears/), { target: { value: "Bea" } });
    fireEvent.click(screen.getByRole("button", { name: "Find me" }));
    await screen.findByRole("button", { name: "Not you?" });
    expect(net.status).toHaveBeenCalledOnce();
    expect(screen.queryByText("Project enclosure")).not.toBeInTheDocument();
    expect(revealRequestCapabilities("a").records.map((row) => row.token)).toEqual(expect.arrayContaining(["current-token", "old-printer-secret"]));
  });

  it.each(["person", "actor", "unmount"] as const)("does not save an already dispatched receipt after %s changes", async (departure) => {
    const held = deferred<Response>(); net.create.mockReturnValueOnce(held.promise);
    const view = mountServiceForm(net); title(); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    if (departure === "person") view.visit({ identity: { name: personB.name, checkin_mid: personB.mid } });
    else if (departure === "actor") act(() => setAccessToken(accessToken("actor-two", { user_id: 2 })));
    else view.unmount();
    await act(async () => held.resolve(json({ public_token: "stale-service", status: "pending" })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).not.toBe("pending"));
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
  });

  it("does not save a failed service submission", async () => {
    net.create.mockResolvedValueOnce(json({ detail: "Not admitted" }, 400));
    mountServiceForm(net); title(); submit();
    expect(await screen.findByText("Not admitted")).toBeVisible();
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
  });

  it("revokes an offline queued mutation before dispatch when its person visit has ended", async () => {
    const view = mountServiceForm(net);
    onlineManager.setOnline(false);
    title(); submit();
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.isPaused).toBe(true));
    view.visit({ identity: { name: personB.name, checkin_mid: personB.mid } });
    act(() => onlineManager.setOnline(true));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(net.create).not.toHaveBeenCalled(); expect(net.presign).not.toHaveBeenCalled();
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
  });
});
