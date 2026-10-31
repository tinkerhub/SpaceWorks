import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, attach, body, choose, deferred, field, genericType, json, mountServiceRoute,
  personB, printerType, rosterMatch, serviceNetwork, settle, submit, title,
  type ServiceNetwork } from "../../test/serviceOwnershipHarness";
import { PublicMachineServicePage } from "./PublicMachineServicePage";

let net: ServiceNetwork;
beforeEach(() => { net = serviceNetwork(); });
afterEach(() => { net.dispose(); });
async function confirm(name = "Ada typed") {
  field(/Your name, as it appears/, name);
  fireEvent.click(screen.getByRole("button", { name: "Find me" }));
  await screen.findByRole("button", { name: "Not you?" });
}

describe("actual shared service page semantic visits", () => {
  it("resets canonical check-in, private draft/files and lookup results before paint on A→B→A", async () => {
    net.bootstraps.forEach((dto) => { dto.makerspace.request_access = "checked_in"; });
    const view = mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText(/Your name, as it appears/);
    await confirm(); title("Private canonical A"); attach();
    expect(screen.getByText(rosterMatch.name)).toBeVisible();
    expect(screen.getByText(rosterMatch.project_name)).toBeVisible();
    view.frames.length = 0;
    view.navigate("/m/b/service?type=11");
    await screen.findByLabelText(/Your name, as it appears/);
    expect(screen.getByLabelText(/Your name, as it appears/)).toHaveValue("");
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    view.navigate("/m/a/service?type=11");
    expect(screen.getByLabelText(/Your name, as it appears/)).toHaveValue("");
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Not you?" })).not.toBeInTheDocument();
    expect(view.frames.length).toBeGreaterThan(0);
    for (const frame of view.frames) {
      expect(frame.inputs).not.toContain("Private canonical A");
      expect(frame.text).not.toContain(rosterMatch.name);
      expect(frame.text).not.toContain(rosterMatch.project_name);
      expect(frame.text).not.toContain("private.pdf");
    }
    // A result list is also visit-owned, even without a canonical selection.
    net.lookup.mockResolvedValue(json([rosterMatch, personB]));
    field(/Your name, as it appears/, "namesakes");
    fireEvent.click(screen.getByRole("button", { name: "Find me" }));
    await screen.findByText(personB.name);
    view.navigate("/m/b/service?type=11");
    expect(screen.queryByText(personB.name)).not.toBeInTheDocument();
    view.navigate("/m/a/service?type=11");
    expect(screen.queryByText(personB.name)).not.toBeInTheDocument();
  });

  it("keeps check-in typing mounted while changing a confirmed person clears private details", async () => {
    net.bootstraps.get("a")!.makerspace.request_access = "checked_in";
    mountServiceRoute(net, <PublicMachineServicePage />);
    const input = await screen.findByLabelText(/Your name, as it appears/);
    field(/Your name, as it appears/, "A");
    expect(screen.getByLabelText(/Your name, as it appears/)).toBe(input);
    field(/Your name, as it appears/, "Ada");
    expect(input).toHaveValue("Ada");
    expect(screen.getByLabelText(/Your name, as it appears/)).toBe(input);
    await confirm(); title(); attach();
    fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toBeDisabled();
    net.lookup.mockResolvedValue(json([personB]));
    await confirm("Bea typed");
    title("Bea description"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    expect(body(net.create.mock.calls[0])).toMatchObject({
      name: personB.name, checkin_mid: personB.mid, title: "Bea description", file_ids: [],
    });
  });

  it("preserves a current draft across stable catalog object refreshes but resets on a type round trip", async () => {
    const view = mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText("Title"); title(); attach();
    act(() => view.client.setQueryData(["public-service-types", "a"], structuredClone([genericType, printerType])));
    expect(screen.getByLabelText("Title")).toHaveValue("Private A project");
    expect(screen.getByText("private.pdf")).toBeVisible();
    choose("Machine type", "3D Printer");
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    field(/^Slicer settings/, "Private settings");
    choose("Machine type", "Laser cutter");
    expect(screen.getByLabelText("Title")).toHaveValue("");
    choose("Machine type", "3D Printer");
    expect(screen.getByLabelText(/^Slicer settings/)).toHaveValue("");
  });

  it("creates fresh visits for changed request policy and real auth epochs", async () => {
    const view = mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText("Title"); title(); attach();
    const bootstrap = structuredClone(net.bootstraps.get("a")!);
    bootstrap.makerspace.request_access = "checked_in";
    act(() => view.client.setQueryData(["tenant-bootstrap", "a"], structuredClone(bootstrap)));
    // Query observers deliver cache notifications asynchronously; wait for the new policy render.
    await screen.findByLabelText(/Your name, as it appears/);
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
    await confirm(); title("Epoch A"); attach();
    act(() => { setAccessToken(accessToken("service-B", { user_id: 2 })); });
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText(/Your name, as it appears/)).toHaveValue("");
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.queryByText("private.pdf")).not.toBeInTheDocument();
  });

  it("treats defaultPrinter changes as visits even when the selected catalog id stays the same", async () => {
    const view = mountServiceRoute(net, <PublicMachineServicePage />, "/m/a/service?type=22");
    await screen.findByLabelText("Title"); title(); field(/^Slicer settings/, "Private settings");
    view.redraw(<PublicMachineServicePage defaultPrinter />);
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText(/^Slicer settings/)).toHaveValue("");
    title("New printer draft");
    view.redraw(<PublicMachineServicePage />);
    expect(screen.getByLabelText("Title")).toHaveValue("");
  });

  it("releases a disappeared form's selector but late A failure/cleanup cannot unlock a pending B", async () => {
    const old = deferred<Response>(), current = deferred<Response>();
    net.presign.mockReturnValueOnce(old.promise);
    net.create.mockReturnValueOnce(current.promise);
    const view = mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText("Title"); title(); attach(); submit();
    await waitFor(() => expect(net.presign).toHaveBeenCalledOnce());
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeDisabled();
    act(() => view.client.setQueryData(["public-service-types", "a"], structuredClone([printerType])));
    await waitFor(() => expect(screen.queryByLabelText("Title")).not.toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeEnabled();
    choose("Machine type", "3D Printer"); title("B still pending"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    await settle(() => old.reject(new Error("Obsolete A error")));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("error"));
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeDisabled();
    expect(screen.getByLabelText("Title")).toHaveValue("B still pending");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.queryByText("Obsolete A error")).not.toBeInTheDocument();
    expect(net.storage).not.toHaveBeenCalled();
    await settle(() => current.resolve(json({ public_token: "b-token", status: "pending" })));
    await screen.findByText("Request submitted");
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeEnabled();
  });

  it("keeps unpublished types and off modules gated, including cached printer types", async () => {
    net.types.mockResolvedValue(json({ results: [genericType], next: null }));
    const view = mountServiceRoute(net, <PublicMachineServicePage />, "/m/a/service?type=999");
    await screen.findByText("That machine type is unavailable. Choose another type.");
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    const bootstrap = structuredClone(net.bootstraps.get("a")!);
    bootstrap.modules = ["machines", "machine_service"];
    act(() => {
      view.client.setQueryData(["tenant-bootstrap", "a"], bootstrap);
      view.client.setQueryData(["public-service-types", "a"], [genericType, printerType]);
    });
    view.navigate("/m/a/service?type=22");
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    choose("Machine type", "Laser cutter");
    expect(screen.getByLabelText("Title")).toBeEnabled();
    net.create.mockResolvedValueOnce(json({ detail: "Service requests disabled" }, 403));
    title("Server still decides"); submit();
    expect(await screen.findByText("Service requests disabled")).toBeVisible();
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    act(() => view.client.setQueryData(["tenant-bootstrap", "a"], structuredClone({ ...bootstrap, modules: ["machines"] })));
    expect(await screen.findByText("No service types available")).toBeVisible();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Service request status" })).not.toBeInTheDocument();
    expect(net.create).toHaveBeenCalledOnce();
    expect(net.presign).not.toHaveBeenCalled();
  });

  it("retains a successful token/banner after internal field reset and finish; old completion cannot replace B", async () => {
    const old = deferred<Response>();
    net.create.mockReturnValueOnce(old.promise).mockResolvedValueOnce(json({ public_token: "b-token", status: "pending" }));
    const view = mountServiceRoute(net, <PublicMachineServicePage />);
    await screen.findByLabelText("Title"); title("Old A"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledOnce());
    view.navigate("/m/b/service?type=11");
    await screen.findByLabelText("Title"); title("Current B"); submit();
    await screen.findByText("Request submitted");
    expect(screen.getByLabelText("Title")).toHaveValue("");
    await waitFor(() => expect(screen.getByLabelText("Title")).toBeEnabled());
    expect(screen.getByRole("link", { name: "Your private status link" })).toHaveAttribute("href", "/m/b/machine-service?token=b-token");
    await settle(() => old.resolve(json({ public_token: "obsolete-a-token", status: "pending" })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("success"));
    expect(screen.getByText("Request submitted")).toBeVisible();
    expect(screen.getByRole("link", { name: "Your private status link" })).toHaveAttribute("href", "/m/b/machine-service?token=b-token");
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("b-token");
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
    title("B retry after finish"); submit();
    await waitFor(() => expect(net.create).toHaveBeenCalledTimes(3));
  });
});
