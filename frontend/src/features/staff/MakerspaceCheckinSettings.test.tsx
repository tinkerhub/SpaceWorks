import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import { ToastProvider } from "../../components/ui";
import { type CheckinSettings, MakerspaceCheckinSettings } from "./MakerspaceCheckinSettings";
import type { Makerspace } from "./panels/shared";

const makerspace = { id: 7, name: "Forge", public_code: "forge", slug: "forge", enabled_modules: [] } as unknown as Makerspace;
const PATH = "/admin/makerspaces/7/checkin-settings";

function settings(overrides: Partial<CheckinSettings> = {}): CheckinSettings {
  return {
    public_request_mode: "checked_in",
    request_access: "checked_in",
    membership_installed: false,
    checkin_space_id: 3,
    checkin_api_url: "",
    checkin_required_purpose: "",
    checkin_provider_name: "",
    deployment: { api_url: "https://checkin.example.org/active", required_purpose: "Working on a project", provider_name: "Maker Gate" },
    effective: { api_url_source: "deployment", required_purpose: "Working on a project", provider_name: "Maker Gate" },
    ...overrides,
  };
}

function respond(current: CheckinSettings, extra: Record<string, unknown> = {}) {
  staffRequest.mockImplementation((path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    if (key in extra) return Promise.resolve(extra[key]);
    return Promise.resolve(current);
  });
}

function renderCard(canManageMakerspace = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MakerspaceCheckinSettings makerspace={makerspace} canManageMakerspace={canManageMakerspace} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("Check-in settings card", () => {
  it("shows the roster fields with the deployment defaults as placeholders", async () => {
    respond(settings());
    renderCard();

    const url = await screen.findByLabelText("Roster URL");
    expect(url).toHaveAttribute("placeholder", "https://checkin.example.org/active");
    expect(screen.getByLabelText("Required purpose")).toHaveAttribute("placeholder", "Working on a project");
    expect(screen.getByLabelText("Upstream space ID")).toHaveValue(3);
  });

  it("saves the roster and confirms with a toast", async () => {
    respond(settings(), { [`PATCH ${PATH}`]: settings({ checkin_api_url: "https://roster.example.net/now" }) });
    renderCard();

    fireEvent.change(await screen.findByLabelText("Roster URL"), { target: { value: " https://roster.example.net/now " } });
    fireEvent.change(screen.getByLabelText("Check-in system name"), { target: { value: "Space Pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Save check-in settings" }));

    expect(await screen.findByText("Check-in settings saved")).toBeInTheDocument();
    const patch = staffRequest.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patch?.[0]).toBe(PATH);
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({
      public_request_mode: "checked_in",
      checkin_api_url: "https://roster.example.net/now",
      checkin_required_purpose: "",
      checkin_provider_name: "Space Pass",
      checkin_space_id: 3,
    });
  });

  it("tests the typed URL and explains a failure", async () => {
    respond(settings(), {
      [`POST ${PATH}/test`]: { ok: false, rows: 0, space_rows: null, code: "not_json", reason: "The roster didn't answer with JSON." },
    });
    renderCard();

    fireEvent.change(await screen.findByLabelText("Roster URL"), { target: { value: "https://roster.example.net/now" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByText("The roster didn't answer with JSON.")).toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith(`${PATH}/test`, {
      method: "POST",
      body: JSON.stringify({ checkin_api_url: "https://roster.example.net/now" }),
    });
  });

  it("reports how many people the roster lists on success", async () => {
    respond(settings(), { [`POST ${PATH}/test`]: { ok: true, rows: 12, space_rows: 4, code: "", reason: "" } });
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));

    expect(await screen.findByText(/Read 12 people checked in/)).toHaveTextContent("4 at this space ID.");
  });

  it("hides the roster fields when the makerspace is not in check-in mode", async () => {
    respond(settings({ public_request_mode: "disabled", request_access: "accounts" }));
    renderCard();

    expect(await screen.findByRole("button", { name: "Save check-in settings" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Roster URL")).toBeNull();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
  });

  it("is hidden entirely from non-managers when check-in is off", async () => {
    respond(settings({ public_request_mode: "disabled", request_access: "accounts" }));
    renderCard(false);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(PATH));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Check-in")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save check-in settings" })).toBeNull();
  });

  it("is read-only for non-managers in check-in mode", async () => {
    respond(settings({ checkin_api_url: "https://roster.example.net/now" }));
    renderCard(false);

    expect(await screen.findByLabelText("Roster URL")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save check-in settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
    expect(screen.getByText("Only staff who manage this makerspace can change this.")).toBeInTheDocument();
  });
});
