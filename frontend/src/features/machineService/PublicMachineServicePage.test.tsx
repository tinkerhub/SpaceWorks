import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StructuredApiError } from "../../lib/api";
import { accessToken } from "../../test/accessTokens";
import { deferred, genericType, printerType, serviceStatus } from "./serviceTestFixtures";

const { fetchServiceTypes, fetchServiceStatus, submitServiceRequest, presignServiceUpload, uploadToStorage,
  getAccessToken, refreshAccessToken, state } = vi.hoisted(() => ({
  fetchServiceTypes: vi.fn(), fetchServiceStatus: vi.fn(), submitServiceRequest: vi.fn(),
  presignServiceUpload: vi.fn(), uploadToStorage: vi.fn(), getAccessToken: vi.fn(), refreshAccessToken: vi.fn(),
  state: { modules: ["machines", "machine_service", "printing", "member_accounts"], loading: false,
    bootstrapLoading: false, bootstrapError: null as Error | null },
}));
vi.mock("./publicApi", async () => ({ ...await vi.importActual<typeof import("./publicApi")>("./publicApi"),
  fetchServiceTypes, fetchServiceStatus, submitServiceRequest, presignServiceUpload }));
vi.mock("../printing/publicApi", async () => ({ ...await vi.importActual<typeof import("../printing/publicApi")>("../printing/publicApi"), uploadToStorage }));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), getAccessToken, refreshAccessToken }));
vi.mock("../../lib/modules", () => ({ useModules: () => ({ loading: state.loading,
  modules: new Set(state.modules), moduleEnabled: (key: string) => state.modules.includes(key) }) }));
vi.mock("../inventory/useMakerspacePublic", () => ({ useMakerspacePublic: () => ({
  makerspaceSlug: "forge", displayName: "Forge", header: { homePath: "/m/forge", name: "Forge" },
  tenantPath: (path = "") => `/m/forge${path ? `/${path}` : ""}`,
  bootstrap: { makerspace: {} },
  bootstrapQuery: { isLoading: state.bootstrapLoading, error: state.bootstrapError, refetch: vi.fn() },
}) }));
import { PublicMachineServicePage } from "./PublicMachineServicePage";
import { PublicPrintRequestPage } from "../printing/PublicPrintRequestPage";

function renderPage(path = "/m/forge/machine-service") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/m/:slug/machine-service" element={<PublicMachineServicePage />} />
    <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
  </Routes></MemoryRouter></QueryClientProvider>);
  return { ...view, client };
}
async function choose(name: string) {
  fireEvent.click(await screen.findByRole("combobox", { name: "Machine type" }));
  fireEvent.click(screen.getByRole("option", { name }));
}
function title(value = "Enclosure") { fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value } }); }
function submit() { fireEvent.click(screen.getByRole("button", { name: "Submit service request" })); }

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  state.modules = ["machines", "machine_service", "printing", "member_accounts"];
  state.loading = state.bootstrapLoading = false;
  state.bootstrapError = null;
  fetchServiceTypes.mockReset().mockResolvedValue([genericType, printerType]);
  fetchServiceStatus.mockReset().mockResolvedValue(serviceStatus);
  submitServiceRequest.mockReset().mockResolvedValue({ public_token: "private-token", status: "pending" });
  presignServiceUpload.mockReset().mockResolvedValue({ queue_id: 8, file_id: 17, upload: { url: "https://objects.example", fields: {} } });
  uploadToStorage.mockReset().mockResolvedValue(undefined);
  getAccessToken.mockReset().mockReturnValue("");
  refreshAccessToken.mockReset().mockImplementation(async () => {
    getAccessToken.mockReturnValue(accessToken("service-restored-member"));
    return true;
  });
});

afterEach(() => { vi.useRealTimers(); });

async function advanceStatusTime(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  // Query notifications can be scheduled by the React commit at the end of act.
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
}

describe("public machine service page", () => {
  it("selects types by id and submits a successful generic proposal with a private tracker", async () => {
    renderPage();
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
    await choose("Laser cutter");
    title();
    fireEvent.change(screen.getByLabelText(/^description/i), { target: { value: "Cut panels" } });
    fireEvent.change(screen.getByLabelText(/^source link/i), { target: { value: "https://example.test/design" } });
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledWith("forge", expect.objectContaining({ machine_type_id: 11,
      title: "Enclosure", description: "Cut panels", source_link: "https://example.test/design" })));
    expect(await screen.findByText("Request submitted")).toBeVisible();
    expect(screen.getByRole("link", { name: "Your private status link" })).toHaveAttribute("href", "/m/forge/machine-service?token=private-token");
    expect(await screen.findByText("Project enclosure")).toBeVisible();
    expect(fetchServiceStatus).toHaveBeenCalledWith("private-token");
  });

  it("honors Machines type preselection and the /print wrapper defaults to the printer", async () => {
    const first = renderPage("/m/forge/machine-service?type=11");
    expect(await screen.findByLabelText(/^description/i)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Machine type" })).toHaveTextContent("Laser cutter");
    first.unmount();
    renderPage("/m/forge/print");
    expect(await screen.findByLabelText(/slicer settings/i)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Machine type" })).toHaveTextContent("3D Printer");
    title();
    submit();
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledWith("forge", expect.objectContaining({ machine_type_id: 22, quantity: 1, consumable_pool_id: null })));
  });

  it("shows an unavailable preselection without silently choosing a different type", async () => {
    renderPage("/m/forge/machine-service?type=999");
    expect(await screen.findByText(/that machine type is unavailable/i)).toBeVisible();
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
    await choose("Laser cutter");
    expect(screen.getByLabelText(/^title$/i)).toBeEnabled();
  });

  it("resets printer fields, files and submission errors when the selected type changes", async () => {
    submitServiceRequest.mockRejectedValue(new Error("Printer capacity unavailable"));
    renderPage("/m/forge/machine-service?type=22");
    await screen.findByLabelText(/^title$/i);
    title();
    fireEvent.change(screen.getByLabelText(/slicer settings/i), { target: { value: "Use supports" } });
    fireEvent.change(screen.getByLabelText(/model, cad/i), { target: { files: [new File(["solid"], "old.stl", { type: "model/stl" })] } });
    submit();
    expect(await screen.findByText("Printer capacity unavailable")).toBeVisible();
    await choose("Laser cutter");
    expect(screen.getByLabelText(/^title$/i)).toHaveValue("");
    expect(screen.queryByText("old.stl")).not.toBeInTheDocument();
    expect(screen.queryByText("Printer capacity unavailable")).not.toBeInTheDocument();
    await choose("3D Printer");
    expect(screen.getByLabelText(/slicer settings/i)).toHaveValue("");
    expect(screen.getByLabelText(/^quantity$/i)).toHaveValue(1);
    expect(screen.queryByText("old.stl")).not.toBeInTheDocument();
  });

  it("disables the type selector while uploading and submitting", async () => {
    const upload = deferred<void>();
    const request = deferred<{ public_token: string; status: string }>();
    uploadToStorage.mockReturnValue(upload.promise);
    submitServiceRequest.mockReturnValue(request.promise);
    renderPage("/m/forge/machine-service?type=11");
    await screen.findByLabelText(/^title$/i);
    title();
    fireEvent.change(screen.getByLabelText(/^attachments/i), { target: { files: [new File(["%PDF-"], "plan.pdf", { type: "application/pdf" })] } });
    submit();
    await waitFor(() => expect(uploadToStorage).toHaveBeenCalledOnce());
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeDisabled();
    await act(async () => upload.resolve());
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledOnce());
    expect(screen.getByRole("combobox", { name: "Machine type" })).toBeDisabled();
    await act(async () => request.resolve({ public_token: "saved", status: "pending" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Machine type" })).toBeEnabled());
  });

  it("waits for the refresh-cookie probe before showing sign-in or enabling a form", async () => {
    const probe = deferred<boolean>();
    refreshAccessToken.mockReturnValue(probe.promise);
    renderPage("/m/forge/machine-service?type=11");
    expect(await screen.findByLabelText("Checking sign-in")).toBeVisible();
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in/i })).not.toBeInTheDocument();
    await act(async () => probe.resolve(false));
    expect(await screen.findByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/m/forge/member");
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
  });

  it("renders generic in_progress status and keeps old printer token links working", async () => {
    fetchServiceStatus.mockResolvedValue({ ...serviceStatus, status: "in_progress", started_at: "2026-10-01T09:01:00Z", estimated_minutes: 20 });
    renderPage("/m/forge/print?token=legacy-token");
    expect(await screen.findByText("Project enclosure")).toBeVisible();
    expect(screen.getByText("Current status:").parentElement).toHaveTextContent("in progress");
    expect(fetchServiceStatus).toHaveBeenCalledWith("legacy-token");
    expect(screen.queryByText("Printing", { exact: true })).not.toBeInTheDocument();
  });

  it("reports status errors without losing the request form", async () => {
    fetchServiceStatus.mockRejectedValue(new Error("Request token was not found"));
    renderPage("/m/forge/machine-service?type=11&token=missing");
    expect(await screen.findByText("Request token was not found")).toBeVisible();
    expect(screen.getByLabelText(/^title$/i)).toBeEnabled();
  });

  it.each([new Error("Network unavailable"), new StructuredApiError(503, { detail: "Status temporarily unavailable" })])(
    "recovers status through Retry status after a temporary failure: %s", async (error) => {
      vi.useFakeTimers();
      fetchServiceStatus.mockReset().mockResolvedValueOnce(serviceStatus).mockRejectedValueOnce(error)
        .mockResolvedValueOnce({ ...serviceStatus, status: "in_progress" })
        .mockResolvedValue({ ...serviceStatus, status: "completed" });
      const view = renderPage("/m/forge/machine-service?token=private-token");
      try {
        await advanceStatusTime(1);
        expect(screen.getByText("Current status:").parentElement).toHaveTextContent("pending");
        expect(fetchServiceStatus).toHaveBeenCalledTimes(1);
        await advanceStatusTime(89_000);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(1);
        await advanceStatusTime(1_100);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(2);
        expect(screen.getByText(error.message)).toBeVisible();
        expect(screen.getByRole("button", { name: "Retry status" })).toBeEnabled();
        expect(view.container.textContent).not.toContain("private-token");
        await advanceStatusTime(180_000);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(2);
        fireEvent.click(screen.getByRole("button", { name: "Retry status" }));
        await advanceStatusTime(1);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(3);
        expect(fetchServiceStatus).toHaveBeenLastCalledWith("private-token");
        expect(screen.queryByText(error.message)).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Retry status" })).not.toBeInTheDocument();
        expect(screen.getByText("Current status:").parentElement).toHaveTextContent("in progress");
        await advanceStatusTime(29_000);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(3);
        await advanceStatusTime(1_100);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(4);
        expect(screen.getByText("Current status:").parentElement).toHaveTextContent("completed");
        await advanceStatusTime(180_000);
        expect(fetchServiceStatus).toHaveBeenCalledTimes(4);
      } finally { view.unmount(); view.client.clear(); }
    },
  );

  it.each([403, 404])("does not poll after a terminal token error (%s)", async (status) => {
    vi.useFakeTimers();
    fetchServiceStatus.mockRejectedValue(new StructuredApiError(status, { detail: "Status link unavailable" }));
    const view = renderPage("/m/forge/machine-service?token=private-token");
    try {
      await advanceStatusTime(1);
      expect(screen.getByText("Status link unavailable")).toBeVisible();
      await advanceStatusTime(180_000);
      expect(fetchServiceStatus).toHaveBeenCalledTimes(1);
      expect(view.container.textContent).not.toContain("private-token");
    } finally { view.unmount(); view.client.clear(); }
  });

  it.each(["moduleoff", "no-token"])("never fetches or polls status with %s", async (mode) => {
    vi.useFakeTimers();
    if (mode === "moduleoff") state.modules = ["machines"];
    const view = renderPage(`/m/forge/machine-service${mode === "moduleoff" ? "?token=private-token" : ""}`);
    try {
      await advanceStatusTime(180_000);
      expect(fetchServiceStatus).not.toHaveBeenCalled();
    } finally { view.unmount(); view.client.clear(); }
  });

  it.each(["loading", "empty", "error", "moduleoff"])("shows the %s catalog state without a submission form", async (mode) => {
    if (mode === "loading") fetchServiceTypes.mockReturnValue(new Promise(() => {}));
    if (mode === "empty") fetchServiceTypes.mockResolvedValue([]);
    if (mode === "error") state.bootstrapError = new Error("Bootstrap unavailable");
    if (mode === "moduleoff") state.modules = ["machines"];
    renderPage();
    if (mode === "loading") expect(screen.getByLabelText("Loading service types")).toBeVisible();
    if (mode === "error") expect(await screen.findByText("Service requests didn't load")).toBeVisible();
    if (mode === "empty" || mode === "moduleoff") expect(await screen.findByText("No service types available")).toBeVisible();
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
    if (mode === "moduleoff") expect(fetchServiceTypes).not.toHaveBeenCalled();
  });

  it("surfaces a catalog fetch failure with a retry action", async () => {
    const { StructuredApiError } = await import("../../lib/api");
    fetchServiceTypes.mockRejectedValue(new StructuredApiError(404, { detail: "Catalog unavailable" }));
    renderPage();
    expect(await screen.findByText("Service requests didn't load")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("filters cached printer types when printing is disabled", async () => {
    state.modules = ["machines", "machine_service"];
    renderPage();
    fireEvent.click(await screen.findByRole("combobox", { name: "Machine type" }));
    expect(screen.queryByRole("option", { name: "3D Printer" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Laser cutter" })).toBeVisible();
  });
});
