import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ServiceType } from "./publicApi";
import { deferred, genericType, printerType } from "./serviceTestFixtures";

const { presignServiceUpload, submitServiceRequest, uploadToStorage } = vi.hoisted(() => ({
  presignServiceUpload: vi.fn(), submitServiceRequest: vi.fn(), uploadToStorage: vi.fn(),
}));
vi.mock("./publicApi", async () => ({ ...await vi.importActual<typeof import("./publicApi")>("./publicApi"), presignServiceUpload, submitServiceRequest }));
vi.mock("../printing/publicApi", async () => ({ ...await vi.importActual<typeof import("../printing/publicApi")>("../printing/publicApi"), uploadToStorage }));
import { ServiceRequestForm } from "./ServiceRequestForm";

function renderForm(type: ServiceType = genericType) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onSuccess = vi.fn(), onPendingChange = vi.fn();
  const props = { slug: "forge", type, identity: {}, identityReady: true, onSuccess, onPendingChange };
  const ui = (selected: ServiceType) => <QueryClientProvider client={client}><ServiceRequestForm {...props} type={selected} /></QueryClientProvider>;
  const view = render(ui(type));
  return { ...view, onSuccess, onPendingChange, client, refresh: (next: ServiceType) => view.rerender(ui(next)) };
}
function fillTitle() { fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "  Enclosure  " } }); }
function submit() { fireEvent.click(screen.getByRole("button", { name: "Submit service request" })); }
function attach(label: RegExp, file: File) { fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } }); }
function pickFilament() {
  fireEvent.click(screen.getByRole("combobox", { name: "Filament / material" }));
  fireEvent.click(screen.getByRole("option", { name: "PLA · Blue" }));
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  presignServiceUpload.mockReset().mockResolvedValue({ queue_id: 8, file_id: 17, upload: { url: "https://objects.example", fields: {} } });
  uploadToStorage.mockReset().mockResolvedValue(undefined);
  submitServiceRequest.mockReset().mockResolvedValue({ public_token: "private-token", status: "pending" });
});

describe("uniform service form", () => {
  it("posts a generic project using the type id and description without printer fields", async () => {
    const view = renderForm();
    fillTitle();
    fireEvent.change(screen.getByLabelText(/^description/i), { target: { value: "  Cut plywood panels  " } });
    fireEvent.change(screen.getByLabelText(/^source link/i), { target: { value: "https://example.test/design" } });
    expect(screen.queryByLabelText(/^quantity$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/slicer settings/i)).not.toBeInTheDocument();
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    const [slug, body] = submitServiceRequest.mock.calls[0];
    expect(slug).toBe("forge");
    expect(body).toMatchObject({ machine_type_id: 11, title: "Enclosure", description: "Cut plywood panels", source_link: "https://example.test/design", file_ids: [] });
    for (const field of ["machine_id", "project_brief", "quantity", "material", "consumable_pool_id", "preferred_settings", "capability_payload"]) expect(body).not.toHaveProperty(field);
    expect(presignServiceUpload).not.toHaveBeenCalled();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("private-token", { saved: true, records: [{ kind: "machine", token: "private-token", saved_at: expect.any(Number) }] }));
    expect(screen.getByLabelText(/^title$/i)).toHaveValue("");
  });

  it("accepts printer requests without a queue or filament preference and wraps human Slicer notes", async () => {
    renderForm(printerType);
    fillTitle();
    fireEvent.change(screen.getByLabelText(/slicer settings/i), { target: { value: "  Use supports and 0.2 mm layers  " } });
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({
      machine_type_id: 22, title: "Enclosure", quantity: 1, consumable_pool_id: null, file_ids: [],
      preferred_settings: { notes: "Use supports and 0.2 mm layers" },
    });
    expect(submitServiceRequest.mock.calls[0][1].queue_id).toBeUndefined();
    expect(submitServiceRequest.mock.calls[0][1]).not.toHaveProperty("description");
  });

  it("uploads model and screenshot in order, pins every later call and submits the returned file ids", async () => {
    presignServiceUpload.mockResolvedValueOnce({ queue_id: 8, file_id: 17, upload: { url: "https://objects.example/model" } })
      .mockResolvedValueOnce({ queue_id: 8, file_id: 23, upload: { url: "https://objects.example/screen" } });
    renderForm(printerType);
    fillTitle();
    pickFilament();
    fireEvent.change(screen.getByLabelText(/^quantity$/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/estimated filament/i), { target: { value: "12.5" } });
    const model = new File(["solid"], "part.stl", { type: "model/stl" });
    const screenshot = new File(["image"], "estimate.png", { type: "image/png" });
    attach(/model, cad/i, model);
    attach(/estimated print-time screenshots/i, screenshot);
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(presignServiceUpload.mock.calls.map((call) => call[1])).toEqual([
      expect.objectContaining({ machine_type_id: 22, kind: "stl", filename: "part.stl", content_type: "model/stl", queue_id: undefined }),
      expect.objectContaining({ machine_type_id: 22, kind: "screenshot", filename: "estimate.png", queue_id: 8 }),
    ]);
    expect(uploadToStorage.mock.calls.map((call) => call[1])).toEqual([model, screenshot]);
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({ queue_id: 8, file_ids: [17, 23], consumable_pool_id: 31, material: "PLA", color: "Blue", quantity: 3, estimated_filament_grams: "12.5" });
    await waitFor(() => expect(screen.queryByText("part.stl")).not.toBeInTheDocument());
  });

  it("uploads generic documents with attachment kind and preserves the pin", async () => {
    renderForm();
    fillTitle();
    attach(/^attachments/i, new File(["%PDF-"], "plan.pdf", { type: "application/pdf" }));
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(presignServiceUpload.mock.calls[0][1]).toMatchObject({ machine_type_id: 11, kind: "attachment", content_type: "application/pdf" });
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({ queue_id: 8, file_ids: [17] });
  });

  it("makes a removed filament choice an explicit choose-again error before uploading", async () => {
    const view = renderForm(printerType);
    fillTitle();
    pickFilament();
    attach(/model, cad/i, new File(["solid"], "part.stl", { type: "model/stl" }));
    // Same type, refreshed catalog: React keeps the draft selection even though stock vanished.
    view.refresh({ ...printerType, consumable_pools: [{ id: 32, material: "PETG", color: "Black" }] });
    submit();
    expect(await screen.findByText(/selected filament is no longer available.*choose again/i)).toBeVisible();
    expect(presignServiceUpload).not.toHaveBeenCalled();
    expect(uploadToStorage).not.toHaveBeenCalled();
    expect(submitServiceRequest).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^title$/i)).toHaveValue("  Enclosure  ");
    fireEvent.click(screen.getByRole("combobox", { name: "Filament / material" }));
    fireEvent.click(screen.getByRole("option", { name: "PETG · Black" }));
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledWith("forge", expect.objectContaining({ consumable_pool_id: 32, material: "PETG", color: "Black" })));
  });

  it("stops when a later presign tries to change the queue", async () => {
    presignServiceUpload.mockResolvedValueOnce({ queue_id: 8, file_id: 17, upload: { url: "https://objects.example" } })
      .mockResolvedValueOnce({ queue_id: 9, file_id: 23, upload: { url: "https://objects.example" } });
    renderForm(printerType);
    fillTitle();
    attach(/model, cad/i, new File(["solid"], "part.stl", { type: "model/stl" }));
    attach(/estimated print-time screenshots/i, new File(["png"], "estimate.png", { type: "image/png" }));
    submit();
    expect(await screen.findByText(/upload queue changed/i)).toBeVisible();
    expect(uploadToStorage).toHaveBeenCalledTimes(1);
    expect(submitServiceRequest).not.toHaveBeenCalled();
  });

  it("lets the requester explicitly clear vanished filament when every pool disappears", async () => {
    const view = renderForm(printerType);
    fillTitle();
    pickFilament();
    attach(/model, cad/i, new File(["solid"], "part.stl", { type: "model/stl" }));
    view.refresh({ ...printerType, consumable_pools: [] });
    expect(screen.getByText("No filament currently available")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Filament / material" })).toHaveTextContent("Selected filament unavailable");
    submit();
    expect(await screen.findByText(/selected filament is no longer available.*choose again/i)).toBeVisible();
    expect(presignServiceUpload).not.toHaveBeenCalled();
    expect(uploadToStorage).not.toHaveBeenCalled();
    expect(submitServiceRequest).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("combobox", { name: "Filament / material" }));
    expect(screen.getByRole("option", { name: "Selected filament unavailable" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByRole("option", { name: "No preference" }));
    expect(screen.getByLabelText(/^title$/i)).toHaveValue("  Enclosure  ");
    expect(screen.getByText("part.stl")).toBeVisible();
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledOnce());
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({
      machine_type_id: printerType.id, title: "Enclosure", consumable_pool_id: null, file_ids: [17], queue_id: 8,
    });
    expect(uploadToStorage).toHaveBeenCalledOnce();
    await waitFor(() => expect(view.onSuccess).toHaveBeenCalledWith("private-token", { saved: true, records: [{ kind: "machine", token: "private-token", saved_at: expect.any(Number) }] }));
  });

  it.each(["presign", "bytes", "submit"])("keeps drafts and reports %s failures without claiming success", async (failure) => {
    const view = renderForm();
    const error = new Error(`${failure} unavailable`);
    if (failure === "presign") presignServiceUpload.mockRejectedValue(error);
    if (failure === "bytes") uploadToStorage.mockRejectedValue(error);
    if (failure === "submit") submitServiceRequest.mockRejectedValue(error);
    fillTitle();
    attach(/^attachments/i, new File(["%PDF-"], "plan.pdf", { type: "application/pdf" }));
    submit();
    expect(await screen.findByText(error.message)).toBeVisible();
    expect(screen.getByLabelText(/^title$/i)).toHaveValue("  Enclosure  ");
    expect(screen.getByText("plan.pdf")).toBeVisible();
    expect(view.onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Submit service request" })).toBeEnabled();
    if (failure !== "submit") expect(submitServiceRequest).not.toHaveBeenCalled();
  });

  it("keeps the form disabled throughout byte upload and submission", async () => {
    const bytes = deferred<void>();
    const request = deferred<{ public_token: string; status: string }>();
    uploadToStorage.mockReturnValue(bytes.promise);
    submitServiceRequest.mockReturnValue(request.promise);
    const view = renderForm();
    fillTitle();
    attach(/^attachments/i, new File(["%PDF-"], "plan.pdf", { type: "application/pdf" }));
    submit();
    await waitFor(() => expect(uploadToStorage).toHaveBeenCalledOnce());
    expect(view.onPendingChange).toHaveBeenCalledWith(true, expect.any(Object));
    const admittedAction = view.onPendingChange.mock.calls[0][1];
    expect(screen.getByLabelText(/^title$/i)).toBeDisabled();
    expect(submitServiceRequest).not.toHaveBeenCalled();
    await act(async () => bytes.resolve());
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledOnce());
    expect(screen.getByLabelText(/^title$/i)).toBeDisabled();
    await act(async () => request.resolve({ public_token: "saved", status: "pending" }));
    await waitFor(() => expect(view.onPendingChange).toHaveBeenLastCalledWith(false, admittedAction));
    expect(screen.getByLabelText(/^title$/i)).toBeEnabled();
  });
});
