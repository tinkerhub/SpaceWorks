import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, vi } from "vitest";
import { ToastProvider } from "../components/ui";
import { clearAccessToken, setAccessToken } from "../lib/apiSession";
import { accessToken } from "./accessTokens";

export { held } from "./authOwnership";
export const photo = new File(["image bytes"], "photo.png", { type: "image/png" });
export const pdf = new File(["%PDF-1.7"], "manual.pdf", { type: "application/pdf" });
export const storageUrl = "https://storage.test/staging/file";
export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
export const noContent = () => new Response(null, { status: 204 });
export const staffToken = (actor = "A") => accessToken(actor, {
  surface: "staff", staff_scope: "platform", user_id: actor === "A" ? 1 : 2,
});
export function login(actor = "A") { setAccessToken(staffToken(actor)); }
export function resetUploadSession() {
  localStorage.clear();
  sessionStorage.clear();
  login();
}
export function cleanUploadSession() {
  cleanup(); // Unmount owned object URLs before restoring their browser leaf mocks.
  clearAccessToken();
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
}

export type HttpCall = {
  path: string; method: string; init: RequestInit; body: Record<string, unknown>;
};
/** Only a leaf HTTP responder. Ownership and bearer selection stay in real production code. */
export function http(respond: (call: HttpCall) => Response | Promise<Response>) {
  const calls: HttpCall[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input).replace(/^.*\/api\/v1/, "");
    const call = { path, method: init.method ?? "GET", init,
      body: typeof init.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {} };
    calls.push(call);
    return respond(call);
  });
  vi.stubGlobal("fetch", fetch);
  return { calls, fetch, writes: () => calls.filter((c) => c.method !== "GET" && c.path !== storageUrl) };
}
export const contract = (method = "PUT", key = "staging/file") => ({
  object_key: key,
  upload: { url: storageUrl, method, headers: { "Content-Type": "application/pdf" }, fields: { key, policy: "signed-policy" } },
});
export function imageContract(method = "PUT") {
  return { ...contract(method).upload, headers: { "Content-Type": "image/png" }, object_key: "staging/image" };
}
export function evidenceContract(method = "PUT", id = 51) {
  return { ...imageContract(method), evidence_id: id, upload_url: storageUrl };
}
export function mountStaff(ui: ReactNode, client = new QueryClient({ defaultOptions: {
    queries: { retry: false, gcTime: 0 }, mutations: { retry: false, gcTime: 0 },
  } })) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}><ToastProvider>{children}</ToastProvider></QueryClientProvider>;
  }
  return { ...render(ui, { wrapper: Wrapper }), client };
}
export function chooseFile(label: string, file = pdf) {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}
export function selectFiles(container: HTMLElement, files: File[]) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Missing actual file picker");
  fireEvent.change(input, { target: { files } });
  return input;
}
export async function release<T>(gate: { resolve: (value: T) => void; promise: Promise<T> }, value: T) {
  await act(async () => { gate.resolve(value); await gate.promise; });
}
export function assertStorage(call: HttpCall, file: File, method: string) {
  expect(call.method).toBe(method);
  expect(new Headers(call.init.headers).has("Authorization")).toBe(false);
  expect(new Headers(call.init.headers).has("X-Publishable-Key")).toBe(false);
  if (method === "PUT") {
    expect(call.init.body).toBe(file);
    expect(new Headers(call.init.headers).get("Content-Type")).toBe(file.type || "application/octet-stream");
  } else {
    expect(call.init.body).toBeInstanceOf(FormData);
    const body = call.init.body as FormData;
    expect(body.get("policy")).toBe("signed-policy");
    expect(body.get("file")).toBe(file);
    expect(body.get("key")).toBe("staging/file");
  }
}
