import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Route, Routes, useNavigate, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { tenantPublicRequest, bootstrapTenant } = vi.hoisted(() => ({
  tenantPublicRequest: vi.fn(), bootstrapTenant: vi.fn(),
}));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest, bootstrapTenant,
}));

import { bootstrapFixture, RegressionProviders, regressionClient, rosterMatch } from "../../test/uiRegressionHarness";
import { PublicRequestPanel } from "./PublicRequestPanel";
import { PublicToolScanPanel } from "./PublicToolScanPanel";
import { PublicSelfCheckoutPage } from "./PublicSelfCheckoutPage";

const bMatch = { ...rosterMatch, mid: 900, name: "Bea Canonical", project_name: "B project" };
type Parent = "request" | "tool" | "self-checkout";
const items = [{ productId: 7, name: "Logic analyzer", quantity: 1 }];

function ParentRoute({ parent }: { parent: Parent }) {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  return <>
    <button onClick={() => navigate("/m/b/checkout")}>Visit B</button>
    {parent === "request" ? <PublicRequestPanel makerspaceSlug={slug} items={items} onClear={() => {}} requestAccess="checked_in" />
      : parent === "tool" ? <PublicToolScanPanel makerspaceSlug={slug} requiresCheckin />
        : <PublicSelfCheckoutPage />}
  </>;
}

function mountParent(parent: Parent) {
  const client = regressionClient();
  return render(<RegressionProviders client={client} path="/m/a/checkout">
    <Routes><Route path="/m/:slug/checkout" element={<ParentRoute parent={parent} />} /></Routes>
  </RegressionProviders>);
}

async function confirm(name: string) {
  fireEvent.change(screen.getByLabelText(/your name, as it appears/i), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: "Find me" }));
  await screen.findByRole("button", { name: "Not you?" });
}

const evidenceCalls = () => tenantPublicRequest.mock.calls.filter(([, path]) => String(path).endsWith("/evidence-url"));
function uploadIssue() {
  fireEvent.change(screen.getByLabelText("Issue photo"), {
    target: { files: [new File(["issue evidence"], "issue.jpg", { type: "image/jpeg" })] },
  });
}

beforeEach(() => {
  tenantPublicRequest.mockReset();
  bootstrapTenant.mockReset();
  bootstrapTenant.mockImplementation(({ slug }: { slug: string }) => Promise.resolve(bootstrapFixture(slug)));
  tenantPublicRequest.mockImplementation(async (slug: string, path: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body ?? "{}"));
    if (path === `/public/${slug}/checkin/lookup`) {
      expect(body.name).toBe(slug === "a" ? "ada typed" : "bea typed");
      return [slug === "a" ? rosterMatch : bMatch];
    }
    if (path === `/public/${slug}/tools/evidence-url`) {
      return { evidence_id: slug === "a" ? 91 : 92, upload_url: `https://storage.example/${slug}/issue`, fields: {}, object_key: `${slug}/staging/issue` };
    }
    if (path === `/public/${slug}/requests`) return { public_token: `${slug}-reference` };
    throw new Error(`Unexpected transport: ${slug} ${path}`);
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit) => {
    if (!/^https:\/\/storage\.example\/[ab]\/issue$/.test(String(url)) || options.method !== "POST") {
      throw new Error(`Unexpected storage transport: ${url}`);
    }
    expect(options.body).toBeInstanceOf(FormData);
    return new Response(null, { status: 204 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("actual public parent identity scope", () => {
  it("PublicRequestPanel immediately drops A readiness on B and submits only B's freshly confirmed mid/name", async () => {
    mountParent("request");
    await confirm("ada typed");
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "A bench testing" } });
    expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Visit B" }));
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/your name, as it appears/i)).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
    expect(tenantPublicRequest.mock.calls.filter(([, path]) => String(path).endsWith("/requests"))).toEqual([]);

    await confirm("bea typed");
    expect(screen.getByLabelText("Request purpose")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "B bench testing" } });
    expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByText("b-reference");
    const requests = tenantPublicRequest.mock.calls.filter(([, path]) => String(path).endsWith("/requests"));
    expect(requests).toHaveLength(1);
    expect(requests[0].slice(0, 2)).toEqual(["b", "/public/b/requests"]);
    expect(JSON.parse(requests[0][2].body)).toMatchObject({ name: bMatch.name, checkin_mid: bMatch.mid, requested_for: "B bench testing" });
    expect(JSON.parse(requests[0][2].body)).not.toMatchObject({ name: rosterMatch.name, checkin_mid: rosterMatch.mid });
  });

  it.each(["tool", "self-checkout"] as const)("%s parent blocks B evidence/loan readiness until a fresh B lookup and resets uploaded evidence on identity edits", async (parent) => {
    mountParent(parent);
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    await confirm("ada typed");
    uploadIssue();
    await screen.findByText("Photo uploaded");
    expect(evidenceCalls()).toHaveLength(1);
    expect(JSON.parse(evidenceCalls()[0][2].body)).toMatchObject({ name: rosterMatch.name, checkin_mid: rosterMatch.mid });

    fireEvent.click(screen.getByRole("button", { name: "Visit B" }));
    // Synchronous assertions protect the first render, before a reset effect could help.
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/your name, as it appears/i)).toHaveValue("");
    if (parent === "tool") expect(screen.getByRole("button", { name: "Scan QR with camera" })).toBeDisabled();
    expect(evidenceCalls()).toHaveLength(1);
    expect(tenantPublicRequest.mock.calls.some(([, path]) => /\/tools\/(checkout|return)$/.test(String(path)))).toBe(false);

    await confirm("bea typed");
    expect(screen.getByLabelText("Issue photo")).toBeEnabled();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
    uploadIssue();
    await screen.findByText("Photo uploaded");
    await waitFor(() => expect(evidenceCalls()).toHaveLength(2));
    expect(evidenceCalls()[1].slice(0, 2)).toEqual(["b", "/public/b/tools/evidence-url"]);
    expect(JSON.parse(evidenceCalls()[1][2].body)).toMatchObject({ name: bMatch.name, checkin_mid: bMatch.mid });
    expect(JSON.parse(evidenceCalls()[1][2].body)).not.toMatchObject({ name: rosterMatch.name, checkin_mid: rosterMatch.mid });

    fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Issue photo")).toHaveValue("");
  });
});
