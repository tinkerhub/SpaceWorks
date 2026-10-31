import { useLayoutEffect, useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useParams } from "react-router-dom";
const { apiGet, tenantPublicRequest, bootstrapTenant } = vi.hoisted(() => ({ apiGet: vi.fn(), tenantPublicRequest: vi.fn(), bootstrapTenant: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), apiGet, tenantPublicRequest, bootstrapTenant,
}));
import { setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { bootstrapFixture } from "../../test/uiRegressionHarness";
import { deferred, fillContact, lendingClient, mountLending, publicProduct, resetLendingSession } from "../../test/publicLendingHarness";
import { PublicInventoryPage } from "./PublicInventoryPage";
import { publicInventoryKey } from "./api";
import { usePublicInventory } from "./usePublicInventory";

const inventory = { count: 1, next: null, previous: null, results: [publicProduct()] };
type Paint = { slug: string; cart: boolean; details: boolean; oldProduct: boolean };
function InventoryPaintProbe({ onPaint }: { onPaint: (paint: Paint) => void }) {
  const { slug = "" } = useParams();
  // A passive reset can fool assertions after fireEvent (which flushes effects).
  // Read the committed DOM in layout, before any passive effect can erase a leak.
  useLayoutEffect(() => {
    onPaint({ slug, cart: Array.from(document.querySelectorAll("button")).some((button) => button.textContent === "Clear selection"),
      details: Boolean(document.querySelector('[role="dialog"]')),
      oldProduct: Boolean(document.querySelector('[aria-label="Add Logic analyzer"]')) });
  }, [slug, onPaint]);
  return <PublicInventoryPage />;
}
function SigningInventory() {
  const [, rerender] = useState(0);
  return <><button onClick={() => { setAccessToken(accessToken("same-maker-login")); rerender((n) => n + 1); }}>Sign in</button>
    <PublicInventoryPage /></>;
}
beforeEach(() => {
  resetLendingSession(); apiGet.mockReset(); tenantPublicRequest.mockReset();
  bootstrapTenant.mockImplementation(async ({ slug }: { slug: string }) => {
    const bootstrap = bootstrapFixture(slug);
    bootstrap.makerspace.request_access = "anyone";
    return bootstrap;
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("public inventory route and selection ownership", () => {
  it("reusing /m/:slug removes A cart and open details synchronously on warm A to cold B", async () => {
    const held = deferred<typeof inventory>();
    apiGet.mockReturnValue(held.promise);
    const client = lendingClient();
    client.setQueryData(publicInventoryKey("a", 1, ""), inventory);
    const paint = vi.fn();
    mountLending(<InventoryPaintProbe onPaint={paint} />, client);
    fireEvent.click(screen.getByRole("button", { name: "Add Logic analyzer" }));
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open details for Logic analyzer" }));
    expect(screen.getByRole("dialog", { name: "Logic analyzer" })).toBeInTheDocument();
    // Navigation is outside the modal; invoke the actual route without a keyed test wrapper.
    fireEvent.click(screen.getByText("Visit B"));
    expect(paint).toHaveBeenLastCalledWith({ slug: "b", cart: false, details: false, oldProduct: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Logic analyzer" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Request purpose")).toHaveValue("");
    await act(async () => { held.resolve({ ...inventory, results: [publicProduct(8, "B drill")] }); });
    expect(await screen.findByRole("button", { name: "Add B drill" })).toBeInTheDocument();
    expect(screen.queryByText("Logic analyzer")).not.toBeInTheDocument();
  });

  it("same-maker sign-in preserves the public cart and open product", () => {
    const client = lendingClient();
    client.setQueryData(publicInventoryKey("a", 1, ""), inventory);
    mountLending(<SigningInventory />, client);
    fireEvent.click(screen.getByRole("button", { name: "Add Logic analyzer" }));
    fireEvent.click(screen.getByRole("button", { name: "Open details for Logic analyzer" }));
    fireEvent.click(screen.getByText("Sign in", { selector: "button" }));
    expect(screen.getByRole("dialog", { name: "Logic analyzer" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Quantity of Logic analyzer" })).getByText("1")).toBeInTheDocument();
  });

  it("successful borrow keeps a cart changed after admission and submits the original quantities", async () => {
    const held = deferred<unknown>(); tenantPublicRequest.mockReturnValue(held.promise);
    apiGet.mockImplementation(async (path: string) => path.includes("/categories/") ? [] : inventory);
    const client = lendingClient();
    client.setQueryData(publicInventoryKey("a", 1, ""), inventory);
    mountLending(<PublicInventoryPage />, client);
    fireEvent.click(screen.getByRole("button", { name: "Add Logic analyzer" }));
    fillContact();
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Add Logic analyzer" }));
    await act(async () => { held.resolve({ public_token: "captured-cart-reference", status: "pending_approval" }); });
    expect(await screen.findByText("captured-cart-reference")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Quantity of Logic analyzer" })).getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
    expect(JSON.parse(tenantPublicRequest.mock.calls[0][2].body).items).toEqual([{ product_id: 7, quantity: 1 }]);
  });

  it("a reused inventory observer keeps same-maker placeholders but never carries warm A into cold B", async () => {
    const held = deferred<typeof inventory>();
    apiGet.mockReturnValue(held.promise);
    const client = lendingClient();
    client.setQueryData(publicInventoryKey("a", 1, ""), inventory);
    const view = renderHook(({ slug, page }) => usePublicInventory(slug, page, ""), {
      initialProps: { slug: "a", page: 1 },
      wrapper: ({ children }) => <QueryClientProvider client={client}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>,
    });
    view.rerender({ slug: "a", page: 2 });
    expect(view.result.current.data).toEqual(inventory);
    expect(view.result.current.isPlaceholderData).toBe(true);
    view.rerender({ slug: "b", page: 1 });
    expect(view.result.current.data).toBeUndefined();
    expect(view.result.current.isPlaceholderData).toBe(false);
    await act(async () => { held.resolve({ ...inventory, results: [publicProduct(8, "B drill")] }); });
    await waitFor(() => expect(view.result.current.data?.results[0].name).toBe("B drill"));
  });
});
