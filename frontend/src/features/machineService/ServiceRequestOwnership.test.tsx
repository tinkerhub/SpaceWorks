import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, attach, deferred, json, mountServiceForm, pdf, personB, printerType,
  serviceNetwork, settle, staged, submit, title, type ServiceNetwork } from "../../test/serviceOwnershipHarness";

let net: ServiceNetwork;
beforeEach(() => { net = serviceNetwork(); });
afterEach(() => { net.dispose(); });

describe("service action ownership through the real upload pipeline", () => {
  it("discards a held presign on person change before dispatching raw bytes", async () => {
    const held = deferred<Response>();
    net.presign.mockReturnValueOnce(held.promise);
    const view = mountServiceForm(net);
    title(); attach(); submit();
    await waitFor(() => expect(net.presign).toHaveBeenCalledOnce());
    view.visit({ identity: { name: personB.name, checkin_mid: personB.mid } });
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    await settle(() => held.resolve(json(staged())));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(net.storage).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(screen.queryByText("Service request wasn't submitted")).not.toBeInTheDocument();
    title("Bea project"); submit();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
    expect(JSON.parse(String(net.create.mock.calls[0][1]?.body))).toMatchObject({
      name: personB.name, checkin_mid: personB.mid, title: "Bea project", file_ids: [],
    });
  });

  it("stops after admitted raw bytes when type changes, including remaining files and progress", async () => {
    const bytes = deferred<Response>();
    net.storage.mockReturnValueOnce(bytes.promise);
    const view = mountServiceForm(net);
    title(); attach([pdf("first.pdf"), pdf("second.pdf")]); submit();
    await waitFor(() => expect(net.storage).toHaveBeenCalledOnce());
    view.visit({ type: printerType });
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Quantity")).toHaveValue(1);
    expect(screen.queryByText("first.pdf")).not.toBeInTheDocument();
    await settle(() => bytes.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(net.presign).toHaveBeenCalledOnce();
    expect(net.storage).toHaveBeenCalledOnce();
    expect(net.create).not.toHaveBeenCalled();
    expect(screen.queryByText("Uploaded 1/2")).not.toBeInTheDocument();
    expect(screen.queryByText("Uploading 2/2")).not.toBeInTheDocument();
    expect(view.onSuccess).not.toHaveBeenCalled();
  });

  it("invalidates held presigns at a real distinct-actor epoch even before another render", async () => {
    const held = deferred<Response>();
    net.presign.mockReturnValueOnce(held.promise);
    const view = mountServiceForm(net);
    title(); attach(); submit();
    await waitFor(() => expect(net.presign).toHaveBeenCalledOnce());
    setAccessToken(accessToken("actor-B", { user_id: 2 }));
    await settle(() => held.resolve(json(staged())));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(net.storage).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
    expect(view.onSuccess).not.toHaveBeenCalled();
    view.visit();
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("Service request wasn't submitted")).not.toBeInTheDocument();
  });

  it("does no more work or result publication after unmount during raw storage", async () => {
    const bytes = deferred<Response>();
    net.storage.mockReturnValueOnce(bytes.promise);
    const view = mountServiceForm(net);
    title(); attach([pdf("one.pdf"), pdf("two.pdf")]); submit();
    await waitFor(() => expect(net.storage).toHaveBeenCalledOnce());
    const action = view.onPendingChange.mock.calls[0][1];
    view.unmount();
    expect(view.onPendingChange).toHaveBeenLastCalledWith(false, action);
    await settle(() => bytes.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(net.presign).toHaveBeenCalledOnce();
    expect(net.create).not.toHaveBeenCalled();
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(view.onPendingChange.mock.calls.filter(([pending]) => !pending)).toHaveLength(1);
  });

  it("cannot revive an A action after A→B→A or replace the newer pending progress on rejection/finally", async () => {
    const old = deferred<Response>(), current = deferred<Response>();
    net.presign.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = mountServiceForm(net);
    title("Old A"); attach(); submit();
    await waitFor(() => expect(net.presign).toHaveBeenCalledOnce());
    view.visit({ slug: "b" });
    expect(screen.getByLabelText("Title")).toHaveValue("");
    view.visit({ slug: "a" });
    title("New A"); attach([pdf("current.pdf")]); submit();
    await waitFor(() => expect(net.presign).toHaveBeenCalledTimes(2));
    await settle(() => old.reject(new Error("obsolete presign failure")));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(screen.getByLabelText("Title")).toHaveValue("New A");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.getByText("Uploading 1/1")).toBeVisible();
    expect(screen.getByText("current.pdf")).toBeVisible();
    expect(screen.queryByText("obsolete presign failure")).not.toBeInTheDocument();
    expect(screen.queryByText("Service request wasn't submitted")).not.toBeInTheDocument();
    expect(net.storage).not.toHaveBeenCalled();
    expect(view.onSuccess).not.toHaveBeenCalled();
    await settle(() => current.resolve(json(staged(23))));
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
  });

  it("ignores an already-dispatched final creation while a new person's request remains pending", async () => {
    const old = deferred<Response>(), current = deferred<Response>();
    net.create.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = mountServiceForm(net);
    title("Ada final"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    view.visit({ identity: { name: personB.name, checkin_mid: personB.mid } });
    title("Bea final"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledTimes(2));
    await settle(() => old.resolve(json({ public_token: "obsolete-token", status: "pending" })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("success"));
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Title")).toHaveValue("Bea final");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.queryByText("Service request submitted")).not.toBeInTheDocument();
    await settle(() => current.resolve(json({ public_token: "bea-token", status: "pending" })));
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledExactlyOnceWith("bea-token", { saved: true, records: [{ kind: "machine", token: "bea-token", saved_at: expect.any(Number) }] }));
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Title")).toBeEnabled();
  });
});
