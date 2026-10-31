import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { deferred, genericType, printerType, serviceStatus } from "../machineService/serviceTestFixtures";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../../test/accessTokens";

const {
  fetchServiceTypes,
  fetchServiceStatus,
  lookupCheckin,
  presignServiceUpload,
  submitServiceRequest,
  uploadToStorage,
  useTenantBootstrap,
  getAccessToken,
  refreshAccessToken,
} = vi.hoisted(() => ({
  fetchServiceTypes: vi.fn(),
  fetchServiceStatus: vi.fn(),
  lookupCheckin: vi.fn(),
  presignServiceUpload: vi.fn(),
  submitServiceRequest: vi.fn(),
  uploadToStorage: vi.fn(),
  useTenantBootstrap: vi.fn(),
  getAccessToken: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getAccessToken, refreshAccessToken };
});

vi.mock("./publicApi", async () => ({
  ...await vi.importActual<typeof import("./publicApi")>("./publicApi"), uploadToStorage,
}));
vi.mock("../machineService/publicApi", async () => ({
  ...await vi.importActual<typeof import("../machineService/publicApi")>("../machineService/publicApi"),
  fetchServiceTypes, fetchServiceStatus, presignServiceUpload, submitServiceRequest,
}));
vi.mock("../../lib/modules", () => ({ useModules: () => ({ loading: false,
  moduleEnabled: (key: string) => useTenantBootstrap().data.modules.includes(key),
}) }));

vi.mock("../inventory/api", async () => {
  const actual = await vi.importActual<typeof import("../inventory/api")>(
    "../inventory/api",
  );
  return { ...actual, lookupCheckin };
});

vi.mock("../inventory/usePublicInventory", () => ({ useTenantBootstrap }));

vi.mock("../../lib/tenant", async () => {
  const actual = await vi.importActual<typeof import("../../lib/tenant")>(
    "../../lib/tenant",
  );
  return {
    ...actual,
    useTenant: () => ({
      mode: "central" as const,
      loading: false,
      error: null,
      bootstrap: null,
      slug: "",
      makerspaceId: null,
      modules: new Set<string>(),
    }),
    useTenantPath: (slug: string) => (path = "") => `/m/${slug}${path ? `/${path}` : ""}`,
  };
});

import { PublicMachineServicePage } from "../machineService/PublicMachineServicePage";
import { PublicPrintRequestPage } from "./PublicPrintRequestPage";

const IDENTITY = {
  mid: 443,
  name: "Ada Example",
  avatar: "",
  purpose: "Working on a project",
  project_name: "Metrocard",
  eligible: true,
  reason: "" as const,
};

function renderPage(requestAccess?: "anyone" | "checked_in", path = "/m/forge/print") {
  useTenantBootstrap.mockReturnValue({
    data: {
      makerspace: {
        id: 1,
        name: "Forge",
        slug: "forge",
        public_code: "forge",
        location: "",
        map_url: "",
        logo_url: null,
        cover_image_url: null,
        geofence_enabled: false,
        membership_policy: "request",
        request_access: requestAccess,
      },
      frontend: { type: "central", hostname: "", allowed_origins: [] },
      modules: ["machines", "machine_service", "printing"],
      features: [],
      workflows: [],
      theme: {},
      branding: { display_name: "Forge" },
      email_enabled: false,
      public_api: { base_url: "", publishable_key: "", inventory_path: "" },
    },
    isLoading: false,
    isError: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
          <Route path="/m/:slug/machine-service" element={<PublicMachineServicePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("checked-in public print requests", () => {
  beforeEach(() => {
    fetchServiceTypes.mockReset();
    fetchServiceTypes.mockResolvedValue([printerType]);
    window.localStorage.clear();
    fetchServiceStatus.mockReset().mockResolvedValue(serviceStatus);
    lookupCheckin.mockReset();
    lookupCheckin.mockResolvedValue([IDENTITY]);
    presignServiceUpload.mockReset();
    presignServiceUpload.mockResolvedValue({
      queue_id: 8,
      file_id: 17,
      upload: { url: "https://storage.example/upload", fields: {} },
    });
    uploadToStorage.mockReset();
    uploadToStorage.mockResolvedValue(undefined);
    submitServiceRequest.mockReset();
    submitServiceRequest.mockResolvedValue({ public_token: "print-token", status: "pending" });
    getAccessToken.mockReturnValue("");
    refreshAccessToken.mockReset();
    refreshAccessToken.mockImplementation(async () => {
      getAccessToken.mockReturnValue(accessToken("printer-restored-member"));
      return true;
    });
  });

  it("gates the form and sends identity with every presign and submission", async () => {
    renderPage("checked_in");
    const nameInput = await screen.findByLabelText(/your name/i);
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(await screen.findByLabelText(/^title$/i)).toBeDisabled();

    fireEvent.change(nameInput, { target: { value: "ada example" } });
    fireEvent.click(screen.getByRole("button", { name: /find me/i }));
    await screen.findByText("Metrocard");

    fireEvent.change(screen.getByLabelText(/^title$/i), {
      target: { value: "Bracket" },
    });
    fireEvent.change(screen.getByLabelText(/model, cad/i), {
      target: {
        files: [new File(["solid"], "bracket.stl", { type: "model/stl" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit service request/i }));

    await waitFor(() => expect(presignServiceUpload).toHaveBeenCalledTimes(1));
    expect(presignServiceUpload.mock.calls[0][1]).toMatchObject({
      checkin_mid: 443,
      name: "Ada Example",
    });
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({
      title: "Bracket",
      machine_type_id: printerType.id,
      queue_id: 8,
      file_ids: [17],
      checkin_mid: 443,
      name: "Ada Example",
    });
  });


  it("uses the same checked-in identity for generic attachments and the shared typed POST", async () => {
    fetchServiceTypes.mockResolvedValue([genericType, printerType]);
    renderPage("checked_in", "/m/forge/machine-service?type=11");
    fireEvent.change(await screen.findByLabelText(/your name/i), { target: { value: "Ada Example" } });
    expect(screen.getByLabelText(/^title$/i)).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /find me/i }));
    await screen.findByText("Metrocard");
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "Cut enclosure" } });
    fireEvent.change(screen.getByLabelText(/^description/i), { target: { value: "Plywood panels" } });
    fireEvent.change(screen.getByLabelText(/^attachments/i), {
      target: { files: [new File(["%PDF-"], "drawing.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit service request/i }));
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(presignServiceUpload).toHaveBeenCalledWith("forge", expect.objectContaining({
      machine_type_id: 11, kind: "attachment", checkin_mid: 443, name: "Ada Example",
    }));
    expect(submitServiceRequest).toHaveBeenCalledWith("forge", expect.objectContaining({
      machine_type_id: 11, title: "Cut enclosure", description: "Plywood panels", queue_id: 8,
      file_ids: [17], checkin_mid: 443, name: "Ada Example",
    }));
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });


  it("keeps generic input disabled while check-in is pending or unreadable", async () => {
    const lookup = deferred<typeof IDENTITY[]>();
    lookupCheckin.mockReturnValue(lookup.promise);
    fetchServiceTypes.mockResolvedValue([genericType, printerType]);
    renderPage("checked_in", "/m/forge/machine-service?type=11");
    fireEvent.change(await screen.findByLabelText(/your name/i), { target: { value: "Ada Example" } });
    fireEvent.click(screen.getByRole("button", { name: /find me/i }));
    expect(await screen.findByRole("button", { name: /checking/i })).toBeDisabled();
    expect(screen.getByLabelText(/^title$/i)).toBeDisabled();
    lookup.reject(new Error("Roster unavailable"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not check the check-in list/i);
    expect(screen.getByLabelText(/^title$/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /submit service request/i })).toBeDisabled();
    expect(presignServiceUpload).not.toHaveBeenCalled();
    expect(submitServiceRequest).not.toHaveBeenCalled();
  });

  it("leaves the existing form and request body unchanged for other policies", async () => {
    renderPage();
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
    const title = await screen.findByLabelText(/^title$/i);
    expect(title).toBeEnabled();

    fireEvent.change(title, { target: { value: "Bracket" } });
    fireEvent.click(screen.getByRole("button", { name: /submit service request/i }));
    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));

    const body = submitServiceRequest.mock.calls[0][1];
    expect(body.checkin_mid).toBeUndefined();
    expect(body.name).toBeUndefined();
  });

  it("asks a signed-out visitor to sign in instead of showing the form", async () => {
    refreshAccessToken.mockResolvedValue(false);
    renderPage();

    // `member_accounts` is off in this bootstrap, so there is nowhere to sign in.
    expect(await screen.findByText(/an account is required/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument();
  });

  it("lets quantity be cleared while typing, clamps it, and resets the form after submitting", async () => {
    renderPage();
    const title = await screen.findByLabelText(/^title$/i);
    const quantity = screen.getByLabelText(/^quantity$/i);
    fireEvent.change(title, { target: { value: "Bracket" } });
    fireEvent.change(quantity, { target: { value: "" } });
    expect(quantity).toHaveValue(null);
    fireEvent.blur(quantity);
    expect(quantity).toHaveValue(1);
    fireEvent.change(quantity, { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/model, cad/i), {
      target: { files: [new File(["solid"], "bracket.stl", { type: "model/stl" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit service request/i }));

    await waitFor(() => expect(submitServiceRequest).toHaveBeenCalledTimes(1));
    expect(submitServiceRequest.mock.calls[0][1]).toMatchObject({ title: "Bracket", quantity: 3 });
    await waitFor(() => expect(screen.getByLabelText(/^title$/i)).toHaveValue(""));
    expect(screen.queryByText("bracket.stl")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit service request/i })).toBeDisabled();
  });
});
