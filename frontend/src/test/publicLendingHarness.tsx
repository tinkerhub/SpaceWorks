import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { ToastProvider } from "../components/ui";
import { clearAccessToken, getSessionGeneration, setAccessToken } from "../lib/apiSession";
import type { Product } from "../types/inventory";
import { accessToken } from "./accessTokens";
import { bootstrapFixture, RegressionProviders, regressionClient } from "./uiRegressionHarness";

export { deferred, rosterMatch } from "./uiRegressionHarness";
export const selection = [{ productId: 7, name: "Logic analyzer", quantity: 1 }];
export const nextPerson = {
  mid: 900, name: "Bea Canonical", avatar: "", eligible: true, reason: "" as const,
  purpose: "Working on a project", project_name: "B project",
};
export const photo = () => new File(["photo bytes"], "evidence.jpg", { type: "image/jpeg" });
export const presign = (id = 91) => ({
  evidence_id: id, upload_url: `https://storage.example/${id}`, fields: { key: `staged/${id}` },
  object_key: `staged/${id}`,
});
export const loanResult = (token = "loan-reference") => ({
  public_token: token, status: "issued", items: [{ product_name: "Logic analyzer", quantity: 1 }],
});
export function publicProduct(id = 7, name = "Logic analyzer"): Product {
  return { id, name, description: "Bench instrument", category_name: "Electronics", category_slug: "electronics",
    image_url: "", tracking_mode: "quantity", availability: { mode: "exact_count", count: 4, label: "Available" } };
}

export function resetLendingSession() {
  selection[0].quantity = 1;
  localStorage.clear();
  sessionStorage.clear();
  setAccessToken(accessToken("public-lending-initial"));
  clearAccessToken();
  localStorage.setItem("makerspace.signed-out", "1");
}

export function lendingClient(policy: "anyone" | "checked_in" = "anyone") {
  const client = regressionClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } });
  for (const slug of ["a", "b"]) {
    const bootstrap = bootstrapFixture(slug);
    bootstrap.makerspace.request_access = policy;
    client.setQueryData(["tenant-bootstrap", slug], bootstrap);
    client.setQueryData(["public-request-session", slug, getSessionGeneration()], false);
    client.setQueryData(["public-categories", slug], []);
  }
  return client;
}

function Navigation({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  return <>
    <button onClick={() => navigate("/m/a")}>Visit A</button>
    <button onClick={() => navigate("/m/b")}>Visit B</button>
    {children}
  </>;
}

// One persistent route element: only production boundaries may remount the tested UI.
export function mountLending(children: ReactNode, client = lendingClient()) {
  return { client, ...render(<RegressionProviders client={client}>
    <ToastProvider><Routes><Route path="/m/:slug" element={<Navigation>{children}</Navigation>} /></Routes></ToastProvider>
  </RegressionProviders>) };
}

export function fillContact(purpose = "Bench project") {
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Ada Contact" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
  fireEvent.change(screen.getByLabelText(/^Phone/), { target: { value: "12345" } });
  fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: purpose } });
}
export async function confirmPerson(name = "ada typed") {
  fireEvent.change(screen.getByLabelText(/your name, as it appears/i), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: "Find me" }));
  await screen.findByRole("button", { name: "Not you?" });
}
export async function uploadPhoto(label = "Issue photo") {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [photo()] } });
  // Return uploads can coexist with an issue photo, so inspect the corresponding live region.
  const region = screen.getByLabelText(label).closest("label")?.parentElement?.parentElement;
  if (!region) throw new Error("Missing evidence region");
  await waitFor(() => { if (!region.textContent?.includes("Photo uploaded")) throw new Error("Upload not finished"); });
}
