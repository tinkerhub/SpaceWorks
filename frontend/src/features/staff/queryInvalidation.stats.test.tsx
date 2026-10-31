import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet, tenantPublicRequest, bootstrapTenant } = vi.hoisted(() => ({
  apiGet: vi.fn(), tenantPublicRequest: vi.fn(), bootstrapTenant: vi.fn(),
}));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), apiGet, tenantPublicRequest, bootstrapTenant,
}));
// The device boundary supplies a scanned payload; all checkout/evidence/query logic stays real.
vi.mock("../../components/ui/QrScanner", () => ({
  default: ({ onScan }: { onScan: (payload: string) => void }) => <button onClick={() => onScan("physical-tool-qr")}>Deliver scanner payload</button>,
}));

import { bootstrapFixture, RegressionProviders, regressionClient, rosterMatch } from "../../test/uiRegressionHarness";
import { PublicToolScanPanel } from "../inventory/PublicToolScanPanel";
import { checkoutTool } from "../inventory/selfCheckoutApi";
import { usePublicCategories, usePublicInventory, useTenantBootstrap } from "../inventory/usePublicInventory";
import { publicStatsKey, usePublicStats, type PublicStatsResponse } from "../stats/api";
import { invalidatePublicInventory } from "./queryInvalidation";

let server: Record<string, number>;
function stats(slug: string): PublicStatsResponse {
  const out = server[slug];
  return {
    printing: null,
    hardware: { most_popular: [], tools_out: [], recently_added: [], library: { library_size: 10, currently_out_count: out, available_count: 10 - out } },
    current_loans: out ? [{ item_name: "Logic analyzer", holder_name: slug === "a" ? "Ada Canonical" : "Bea Canonical", due: null, since: null }] : [],
  };
}

function StatsReadout({ slug }: { slug: string }) {
  const query = usePublicStats(slug);
  return <output aria-label={`${slug} public stats`}>{query.data
    ? `${query.data.hardware.library.currently_out_count} out; ${query.data.current_loans.map((loan) => loan.holder_name).join(", ") || "no current loans"}`
    : "loading"}</output>;
}

// Real public list/category/bootstrap observers protect their existing refresh behaviour too.
function RelatedPublicViews() {
  usePublicInventory("a", 1, "");
  usePublicCategories("a");
  useTenantBootstrap("a");
  useQuery({ queryKey: ["public-inventory-detail", "a", 7], queryFn: () => apiGet("/public/a/inventory/7/") });
  return null;
}

// Exercise the documented no-slug consumer contract with the real mutation API and helper.
// Stats keys and fetching belong solely to usePublicStats/publicStatsKey above.
function SluglessCheckoutConsumer() {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => checkoutTool("a", { payload: "physical-tool-qr", evidence_id: 91 }),
    onSuccess: () => invalidatePublicInventory(client),
  });
  return <button disabled={mutation.isPending} onClick={() => mutation.mutate()}>Checkout without cached slug</button>;
}

function statsRequests(slug: string) {
  return apiGet.mock.calls.filter(([path]) => path === `/public/${slug}/stats/`);
}
async function upload(label: "Issue photo" | "Return photo") {
  fireEvent.change(screen.getByLabelText(label), { target: {
    files: [new File(["evidence"], "tool.jpg", { type: "image/jpeg" })],
  } });
  await screen.findByText("Photo uploaded");
}

beforeEach(() => {
  server = { a: 0, b: 0 };
  apiGet.mockReset();
  apiGet.mockImplementation(async (path: string) => {
    const match = path.match(/^\/public\/([ab])\/stats\/$/);
    if (match) return stats(match[1]);
    if (path === "/public/a/inventory/") return { count: 0, next: null, previous: null, results: [] };
    if (path === "/public/a/inventory/categories/") return [];
    if (path === "/public/a/inventory/7/") return { id: 7, name: "Logic analyzer" };
    throw new Error(`Unexpected stats transport: ${path}`);
  });
  bootstrapTenant.mockReset();
  bootstrapTenant.mockImplementation(async ({ slug }: { slug: string }) => bootstrapFixture(slug));
  tenantPublicRequest.mockReset();
  tenantPublicRequest.mockImplementation(async (slug: string, path: string, options: RequestInit) => {
    const body = JSON.parse(String(options.body));
    if (path === `/public/${slug}/checkin/lookup`) return [rosterMatch];
    if (path === `/public/${slug}/tools/evidence-url`) {
      expect(body).toMatchObject({ name: rosterMatch.name, checkin_mid: rosterMatch.mid });
      return { evidence_id: 91, upload_url: "https://storage.example/tool-evidence", fields: {}, object_key: "staging/tool" };
    }
    if (path === `/public/${slug}/tools/checkout` || path === `/public/${slug}/tools/return`) {
      expect(body).toMatchObject({ payload: "physical-tool-qr", evidence_id: 91 });
      server[slug] = path.endsWith("/checkout") ? 1 : 0;
      return { public_token: "loan-reference", status: server[slug] ? "issued" : "returned", items: [] };
    }
    throw new Error(`Unexpected loan transport: ${path}`);
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit) => {
    if (url !== "https://storage.example/tool-evidence" || options.method !== "POST") throw new Error(`Unexpected upload: ${url}`);
    expect(options.body).toBeInstanceOf(FormData);
    return new Response(null, { status: 204 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("public stats warm-cache invalidation", () => {
  it("real tool checkout and return refresh visible warm A stats before 30s while warm B stays untouched", async () => {
    const client = regressionClient();
    expect(client.getDefaultOptions().queries?.staleTime).toBe(30_000);
    for (const slug of ["a", "b"]) client.setQueryData(publicStatsKey(slug), stats(slug));
    const warmedAt = client.getQueryState(publicStatsKey("a"))!.dataUpdatedAt;
    const view = render(<RegressionProviders client={client}>
      <StatsReadout slug="a" /><StatsReadout slug="b" /><RelatedPublicViews />
      <PublicToolScanPanel makerspaceSlug="a" requiresCheckin />
    </RegressionProviders>);
    expect(screen.getByLabelText("a public stats")).toHaveTextContent("0 out; no current loans");
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/public/a/inventory/"));
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/public/a/inventory/categories/"));
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/public/a/inventory/7/"));
    expect(statsRequests("a")).toHaveLength(0);
    expect(statsRequests("b")).toHaveLength(0);
    apiGet.mockClear();

    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "ada typed" } });
    fireEvent.click(screen.getByRole("button", { name: "Find me" }));
    await screen.findByRole("button", { name: "Not you?" });
    await upload("Issue photo");
    fireEvent.click(screen.getByRole("button", { name: "Scan QR with camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Deliver scanner payload" }));
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await screen.findByText("Issued: Tool loan");
    await waitFor(() => expect(screen.getByLabelText("a public stats")).toHaveTextContent("1 out; Ada Canonical"));
    expect(Date.now() - warmedAt).toBeLessThan(30_000);
    expect(statsRequests("a")).toHaveLength(1);
    expect(statsRequests("b")).toHaveLength(0);
    expect(screen.getByLabelText("b public stats")).toHaveTextContent("0 out; no current loans");
    for (const path of ["/public/a/inventory/", "/public/a/inventory/categories/", "/public/a/inventory/7/"]) {
      await waitFor(() => expect(apiGet).toHaveBeenCalledWith(path));
    }
    await waitFor(() => expect(bootstrapTenant).toHaveBeenCalledWith({ slug: "a" }));

    await upload("Return photo");
    fireEvent.change(screen.getByLabelText("Return condition notes"), { target: { value: "Returned clean" } });
    fireEvent.click(screen.getByRole("button", { name: "Return" }));
    await screen.findByText("Returned: Tool loan");
    await waitFor(() => expect(screen.getByLabelText("a public stats")).toHaveTextContent("0 out; no current loans"));
    expect(statsRequests("a")).toHaveLength(2);
    expect(statsRequests("b")).toHaveLength(0);
    expect(Date.now() - warmedAt).toBeLessThan(30_000);
    view.unmount();
    client.clear();
  });

  it("no-slug fallback after the actual checkout API refetches all mounted warm stats", async () => {
    const client = regressionClient();
    for (const slug of ["a", "b"]) client.setQueryData(publicStatsKey(slug), stats(slug));
    const warmedAt = Date.now();
    const view = render(<RegressionProviders client={client}>
      <StatsReadout slug="a" /><StatsReadout slug="b" /><SluglessCheckoutConsumer />
    </RegressionProviders>);
    expect(screen.getByLabelText("a public stats")).toHaveTextContent("0 out");
    expect(screen.getByLabelText("b public stats")).toHaveTextContent("0 out");
    expect(apiGet).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Checkout without cached slug" }));
    await waitFor(() => expect(screen.getByLabelText("a public stats")).toHaveTextContent("1 out; Ada Canonical"));
    await waitFor(() => expect(statsRequests("b")).toHaveLength(1));
    expect(statsRequests("a")).toHaveLength(1);
    expect(screen.getByLabelText("b public stats")).toHaveTextContent("0 out; no current loans");
    expect(Date.now() - warmedAt).toBeLessThan(30_000);
    expect(tenantPublicRequest).toHaveBeenCalledWith("a", "/public/a/tools/checkout", expect.objectContaining({ method: "POST" }));
    view.unmount();
    client.clear();
  });
});
