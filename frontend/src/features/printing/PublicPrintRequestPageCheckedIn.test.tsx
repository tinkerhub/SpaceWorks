import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchPrintQueues,
  fetchPublicConsumablePools,
  fetchPrintStatus,
  lookupCheckin,
  presignPrintUpload,
  submitPrintRequest,
  uploadToStorage,
  useTenantBootstrap,
} = vi.hoisted(() => ({
  fetchPrintQueues: vi.fn(),
  fetchPublicConsumablePools: vi.fn(),
  fetchPrintStatus: vi.fn(),
  lookupCheckin: vi.fn(),
  presignPrintUpload: vi.fn(),
  submitPrintRequest: vi.fn(),
  uploadToStorage: vi.fn(),
  useTenantBootstrap: vi.fn(),
}));

vi.mock("./publicApi", async () => {
  const actual = await vi.importActual<typeof import("./publicApi")>("./publicApi");
  return {
    ...actual,
    fetchPrintQueues,
    fetchPublicConsumablePools,
    fetchPrintStatus,
    presignPrintUpload,
    submitPrintRequest,
    uploadToStorage,
  };
});

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
    useTenantPath: (slug: string) => () => `/m/${slug}`,
  };
});

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

function renderPage(requestAccess?: "anyone" | "checked_in") {
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
      modules: ["machine_service"],
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
      <MemoryRouter initialEntries={["/m/forge/print"]}>
        <Routes>
          <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("checked-in public print requests", () => {
  beforeEach(() => {
    fetchPrintQueues.mockReset();
    fetchPrintQueues.mockResolvedValue([{ id: 8, name: "Printers", description: "" }]);
    fetchPublicConsumablePools.mockReset();
    fetchPublicConsumablePools.mockResolvedValue([]);
    fetchPrintStatus.mockReset();
    lookupCheckin.mockReset();
    lookupCheckin.mockResolvedValue([IDENTITY]);
    presignPrintUpload.mockReset();
    presignPrintUpload.mockResolvedValue({
      file_id: 17,
      upload: { url: "https://storage.example/upload", fields: {} },
    });
    uploadToStorage.mockReset();
    uploadToStorage.mockResolvedValue(undefined);
    submitPrintRequest.mockReset();
    submitPrintRequest.mockResolvedValue({ public_token: "print-token", status: "pending" });
  });

  it("gates the form and sends identity with every presign and submission", async () => {
    renderPage("checked_in");
    const nameInput = await screen.findByLabelText(/your name/i);
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
    fireEvent.click(screen.getByRole("button", { name: /submit print request/i }));

    await waitFor(() => expect(presignPrintUpload).toHaveBeenCalledTimes(1));
    expect(presignPrintUpload.mock.calls[0][1]).toMatchObject({
      checkin_mid: 443,
      name: "Ada Example",
    });
    await waitFor(() => expect(submitPrintRequest).toHaveBeenCalledTimes(1));
    expect(submitPrintRequest.mock.calls[0][1]).toMatchObject({
      title: "Bracket",
      file_ids: [17],
      checkin_mid: 443,
      name: "Ada Example",
    });
  });

  it("leaves the existing form and request body unchanged for other policies", async () => {
    renderPage();
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
    const title = await screen.findByLabelText(/^title$/i);
    expect(title).toBeEnabled();

    fireEvent.change(title, { target: { value: "Bracket" } });
    fireEvent.click(screen.getByRole("button", { name: /submit print request/i }));
    await waitFor(() => expect(submitPrintRequest).toHaveBeenCalledTimes(1));

    const body = submitPrintRequest.mock.calls[0][1];
    expect(body.checkin_mid).toBeUndefined();
    expect(body.name).toBeUndefined();
  });
});
