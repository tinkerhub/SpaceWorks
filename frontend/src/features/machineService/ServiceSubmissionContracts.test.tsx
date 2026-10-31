import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearAccessToken, getAccessToken } from "../../lib/apiSession";
import { accessToken, attach, body, choose, deferred, field, genericType, json, mountServiceForm,
  pdf, printerType, rosterMatch, serviceNetwork, settle, staged, submit, title,
  type ServiceNetwork } from "../../test/serviceOwnershipHarness";

let net: ServiceNetwork;
beforeEach(() => { net = serviceNetwork(); });
afterEach(() => { net.dispose(); });

describe("captured service submission contracts", () => {
  it("submits an exact generic no-file DTO and remains usable after finish", async () => {
    const view = mountServiceForm(net);
    title("  Panel  "); field(/^Description/, "  Cut panels  ");
    field(/^Source link/, " https://design.example/panel ");
    submit();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
    expect(body(net.create.mock.calls[0])).toEqual({ machine_type_id: 11, title: "Panel",
      description: "Cut panels", source_link: "https://design.example/panel", website: "",
      name: rosterMatch.name, checkin_mid: rosterMatch.mid, file_ids: [] });
    expect(net.presign).not.toHaveBeenCalled();
    expect(net.storage).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Title")).toHaveValue("");
    await waitFor(() => expect(screen.getByLabelText("Title")).toBeEnabled());
    title("Second panel"); submit();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledTimes(2));
    expect(body(net.create.mock.calls[1]).title).toBe("Second panel");
  });

  it("captures immutable printer fields, files, identity and policy and pins serial uploads to the first queue", async () => {
    const first = deferred<Response>(), second = deferred<Response>();
    net.presign.mockResolvedValueOnce(json(staged(17))).mockResolvedValueOnce(json(staged(23)));
    net.storage.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const type = structuredClone(printerType);
    const identity = { name: rosterMatch.name, checkin_mid: rosterMatch.mid };
    const view = mountServiceForm(net, { type, identity });
    title("  Enclosure  "); field(/^Project brief/, "  Fit board  ");
    field(/^Slicer settings/, "  Supports, 0.2 mm  ");
    field(/^Source link/, "https://design.example/box");
    choose("Filament / material", "PLA · Blue");
    field("Quantity", "3"); field(/^Estimated filament/, "12.5");
    const model = new File(["solid"], "part.stl", { type: "model/stl" });
    const screenshot = new File(["png"], "time.png", { type: "image/png" });
    attach([model], "Model, CAD, or toolpath files");
    attach([screenshot], "Estimated print-time screenshots (Bambu Lab)");
    submit();
    // Mutable catalog/identity sources and programmatic edits after admission must not
    // become the request. Policy validation itself is deferred by TanStack's mutation.
    type.file_policy.max_bytes = 1;
    type.file_policy.allowed_extensions.length = 0;
    type.consumable_pools[0].material = "PETG";
    identity.name = "Edited after admission";
    field("Title", "Edited draft");
    attach([pdf("later.pdf")], "Model, CAD, or toolpath files");
    await waitFor(() => expect(net.storage).toHaveBeenCalledOnce());
    expect(net.presign).toHaveBeenCalledOnce();
    expect(net.create).not.toHaveBeenCalled();
    expect(body(net.presign.mock.calls[0])).toEqual({ machine_type_id: 22, kind: "stl",
      filename: "part.stl", content_type: "model/stl", name: rosterMatch.name, checkin_mid: rosterMatch.mid });
    expect((net.storage.mock.calls[0][1]?.body as FormData).get("file")).toEqual(model);
    expect((net.storage.mock.calls[0][1]?.body as FormData).get("key")).toBe("staging/17");
    await settle(() => first.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(net.storage).toHaveBeenCalledTimes(2));
    expect(body(net.presign.mock.calls[1])).toEqual({ machine_type_id: 22, queue_id: 8,
      kind: "screenshot", filename: "time.png", content_type: "image/png",
      name: rosterMatch.name, checkin_mid: rosterMatch.mid });
    expect((net.storage.mock.calls[1][1]?.body as FormData).get("file")).toEqual(screenshot);
    expect(net.create).not.toHaveBeenCalled();
    await settle(() => second.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
    expect(body(net.create.mock.calls[0])).toEqual({ machine_type_id: 22, title: "Enclosure",
      project_brief: "Fit board", preferred_settings: { notes: "Supports, 0.2 mm" },
      consumable_pool_id: 31, material: "PLA", color: "Blue", estimated_filament_grams: "12.5", quantity: 3,
      source_link: "https://design.example/box", website: "", name: rosterMatch.name,
      checkin_mid: rosterMatch.mid, queue_id: 8, file_ids: [17, 23] });
    expect(net.presign).toHaveBeenCalledTimes(2);
    expect(net.storage).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("part.stl")).not.toBeInTheDocument();
  });

  it("admits same-tick duplicate submit events exactly once", async () => {
    const held = deferred<Response>();
    net.create.mockReturnValueOnce(held.promise);
    const view = mountServiceForm(net);
    title();
    act(() => { submit(); submit(); });
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    expect(view.onPendingChange.mock.calls.filter(([pending]) => pending)).toHaveLength(1);
    await settle(() => held.resolve(json({ public_token: "one-token", status: "pending" })));
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledExactlyOnceWith("one-token", { saved: true, records: [{ kind: "machine", token: "one-token", saved_at: expect.any(Number) }] }));
    expect(view.onPendingChange).toHaveBeenLastCalledWith(false, view.onPendingChange.mock.calls[0][1]);
  });

  it("keeps current errors and drafts usable for retry, then clears them on success", async () => {
    net.storage.mockResolvedValueOnce(json({ detail: "Storage unavailable" }, 503));
    const view = mountServiceForm(net);
    title("Retry me"); attach(); submit();
    expect(await screen.findByText("Upload failed (503)")).toBeVisible();
    expect(screen.getByLabelText("Title")).toHaveValue("Retry me");
    expect(screen.getByText("private.pdf")).toBeVisible();
    expect(screen.getByRole("button", { name: "Submit service request" })).toBeEnabled();
    expect(net.create).not.toHaveBeenCalled();
    submit();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
    expect(screen.queryByText("Upload failed (503)")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(net.storage).toHaveBeenCalledTimes(2);
    expect(net.create).toHaveBeenCalledOnce();
  });

  it("requires a nonblank title and ready identity before admitting any action", () => {
    const view = mountServiceForm(net, { identityReady: false });
    title("Blocked"); submit();
    expect(view.onPendingChange).not.toHaveBeenCalled();
    view.visit({ identityReady: true });
    title("   "); submit();
    expect(screen.getByRole("button", { name: "Submit service request" })).toBeDisabled();
    expect(view.onPendingChange).not.toHaveBeenCalled();
    expect(net.presign).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
  });

  it("rejects a generic attachment outside the captured type extensions", async () => {
    mountServiceForm(net); title();
    attach([new File(["exe"], "program.exe", { type: "application/octet-stream" })]); submit();
    expect(await screen.findByText("program.exe is not an allowed attachment type.")).toBeVisible();
    expect(net.presign).not.toHaveBeenCalled();
    expect(net.storage).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
  });

  it("rejects a file above the selected type's byte limit before presign", async () => {
    mountServiceForm(net, { type: { ...genericType, file_policy: { ...genericType.file_policy, max_bytes: 1 } } });
    title(); attach(); submit();
    expect(await screen.findByText("private.pdf exceeds the 0 MB file limit.")).toBeVisible();
    expect(net.presign).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
  });

  it("rejects a later queue change before sending that file's bytes or creating the request", async () => {
    net.presign.mockResolvedValueOnce(json(staged(17, 8))).mockResolvedValueOnce(json(staged(23, 9)));
    mountServiceForm(net); title(); attach([pdf("one.pdf"), pdf("two.pdf")]); submit();
    expect(await screen.findByText("The upload queue changed. Please submit again.")).toBeVisible();
    expect(body(net.presign.mock.calls[1]).queue_id).toBe(8);
    expect(net.storage).toHaveBeenCalledOnce();
    expect(net.create).not.toHaveBeenCalled();
  });

  it("keeps a refreshed printer draft but validates its vanished pool before upload", async () => {
    const view = mountServiceForm(net, { type: printerType });
    title(); choose("Filament / material", "PLA · Blue");
    attach([new File(["solid"], "part.stl")], "Model, CAD, or toolpath files");
    view.visit({ type: { ...printerType, consumable_pools: [] } });
    expect(screen.getByLabelText("Title")).toHaveValue("Private A project");
    expect(screen.getByText("part.stl")).toBeVisible(); submit();
    expect(await screen.findByText("Your selected filament is no longer available. Please choose again.")).toBeVisible();
    expect(net.presign).not.toHaveBeenCalled();
    expect(net.create).not.toHaveBeenCalled();
    choose("Filament / material", "No preference"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    expect(body(net.create.mock.calls[0]).consumable_pool_id).toBeNull();
  });

  it("uses an actual valid refresh token response when a current API call retries a 401", async () => {
    clearAccessToken();
    net.create.mockResolvedValueOnce(json({ detail: "Expired" }, 401));
    const view = mountServiceForm(net);
    title("Cookie session"); submit();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("current-token", { saved: true, records: [{ kind: "machine", token: "current-token", saved_at: expect.any(Number) }] }));
    expect(net.refresh).toHaveBeenCalledOnce();
    expect(getAccessToken()).toBe(accessToken("service-refreshed", { user_id: 1 }));
    expect(net.create).toHaveBeenCalledTimes(2);
    expect(new Headers(net.create.mock.calls[1][1]?.headers).get("Authorization"))
      .toBe(`Bearer ${getAccessToken()}`);
    expect(body(net.create.mock.calls[1])).toEqual(body(net.create.mock.calls[0]));
  });
});
