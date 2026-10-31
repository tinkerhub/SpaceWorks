import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { admitUpload } from "../../../../lib/uploadProtocol";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  maintenanceKeys, useDeleteMaintenanceDocument, useFinalizeMaintenanceDocument,
  useMaintenanceDocumentUrl, usePresignMaintenanceDocument,
} from "./maintenanceApi";
import { maintenanceDocument } from "../../../../test/staffDocumentFixtures";
import { cleanUploadSession, contract, held, http, json, login, pdf, release, resetUploadSession } from "../../../../test/staffUploadHarness";

let originalOnline: boolean;
beforeEach(() => { originalOnline = onlineManager.isOnline(); resetUploadSession(); vi.spyOn(window, "open").mockReturnValue(null); });
afterEach(() => { onlineManager.setOnline(originalOnline); cleanUploadSession(); });
type Kind = "presign" | "finalize" | "delete" | "url";
type Mode = "mutate" | "mutateAsync";
function useTask(kind: Kind, resource: number) {
  const presign = usePresignMaintenanceDocument(resource + 10);
  const finalize = useFinalizeMaintenanceDocument(resource, resource + 10);
  const remove = useDeleteMaintenanceDocument(resource, resource + 10);
  const url = useMaintenanceDocumentUrl();
  // Exercise the actual one-argument public wrappers with primitive/default inputs.
  const invoke = (mode: Mode): Promise<unknown> | void => {
    if (kind === "presign") return mode === "mutate" ? presign.mutate(pdf) : presign.mutateAsync(pdf);
    if (kind === "finalize") return mode === "mutate" ? finalize.mutate("staging/original") : finalize.mutateAsync("staging/original");
    if (kind === "delete") return mode === "mutate" ? remove.mutate(81) : remove.mutateAsync(81);
    return mode === "mutate" ? url.mutate(81) : url.mutateAsync(81);
  };
  return { invoke, state: kind === "presign" ? presign : kind === "finalize" ? finalize : kind === "delete" ? remove : url };
}
function setup(kind: Kind) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { ...renderHook(({ resource }) => useTask(kind, resource), { initialProps: { resource: 1 }, wrapper }), client };
}

it.each([
  { kind: "presign" as const, mode: "mutateAsync" as const, departure: "unmount" },
  { kind: "finalize" as const, mode: "mutateAsync" as const, departure: "actor" },
  { kind: "finalize" as const, mode: "mutate" as const, departure: "resource" },
  { kind: "delete" as const, mode: "mutate" as const, departure: "actor" },
  { kind: "url" as const, mode: "mutate" as const, departure: "actor" },
  { kind: "url" as const, mode: "mutateAsync" as const, departure: "unmount" },
])("paused primitive $kind.$mode cannot dispatch an old ID after $departure", async ({ kind, mode, departure }) => {
  onlineManager.setOnline(false);
  const net = http(() => json({ url: "https://private.test/current" }));
  const view = setup(kind);
  let outcome: Promise<unknown> | undefined;
  act(() => { const result = view.result.current.invoke(mode); if (result) outcome = result.catch((error: unknown) => error); });
  await waitFor(() => expect(view.result.current.state.isPaused).toBe(true));
  expect(net.calls).toHaveLength(0);
  if (departure === "actor") { login("B"); view.rerender({ resource: 1 }); }
  else if (departure === "resource") view.rerender({ resource: 2 });
  else view.unmount();
  await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); await outcome; });
  expect(net.calls).toHaveLength(0);
  expect(window.open).not.toHaveBeenCalled();
  expect(view.client.getMutationCache().getAll().some((mutation) => mutation.state.status === "error")).toBe(true);
});

it.each(["actor", "unmount"])("hook-level already-dispatched private URL cannot open after %s", async (departure) => {
  const url = held<Response>();
  const net = http(() => url.promise);
  const view = setup("url");
  let outcome!: Promise<unknown>;
  act(() => { outcome = Promise.resolve(view.result.current.invoke("mutateAsync")).catch((error: unknown) => error); });
  await waitFor(() => expect(net.calls[0]?.path).toBe("/admin/maintenance/log-documents/81/url/"));
  if (departure === "actor") { login("B"); view.rerender({ resource: 1 }); } else view.unmount();
  await release(url, json({ url: "https://private.test/obsolete" }));
  await outcome;
  expect(window.open).not.toHaveBeenCalled();
});

it("current URL resolves a plain DTO and opens the private tab", async () => {
  http(() => json({ url: "https://private.test/current" }));
  const view = setup("url");
  let dto: unknown;
  await act(async () => { dto = await view.result.current.invoke("mutateAsync"); });
  expect(dto).toEqual({ url: "https://private.test/current" });
  expect(Object.keys(dto as object)).toEqual(["url"]);
  expect(window.open).toHaveBeenCalledExactlyOnceWith("https://private.test/current", "_blank", "noopener,noreferrer");
});

it("current finalize returns the unadorned document DTO and retains both invalidations", async () => {
  const net = http(() => json(maintenanceDocument));
  const view = setup("finalize");
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  let dto: unknown;
  await act(async () => { dto = await view.result.current.invoke("mutateAsync"); });
  expect(dto).toEqual(maintenanceDocument);
  expect(Object.keys(dto as object).sort()).toEqual(Object.keys(maintenanceDocument).sort());
  expect(net.calls[0]).toMatchObject({ path: "/admin/maintenance/logs/11/documents/", body: { object_key: "staging/original" } });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logs(1) });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logDocuments(11) });
});

it("current presign and delete primitive calls still dispatch their exact inputs", async () => {
  const net = http((call) => json(call.path.includes("presign") ? contract() : {}));
  const presign = setup("presign");
  let dto: unknown;
  await act(async () => { dto = await presign.result.current.invoke("mutateAsync"); });
  expect(dto).toEqual(contract());
  expect(net.calls[0].body).toEqual({ filename: pdf.name, content_type: pdf.type });
  presign.unmount();
  const remove = setup("delete");
  const invalidate = vi.spyOn(remove.client, "invalidateQueries");
  await act(async () => { await remove.result.current.invoke("mutateAsync"); });
  expect(net.calls[net.calls.length - 1]).toMatchObject({ path: "/admin/maintenance/log-documents/81/", method: "DELETE" });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logs(1) });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: maintenanceKeys.logDocuments(11) });
});

it("a supplied resource/action predicate remains composed with the hook owner during a pause", async () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useFinalizeMaintenanceDocument(1, 11), { wrapper });
  const net = http(() => json(maintenanceDocument));
  let actionCurrent = true;
  const guard = admitUpload(() => actionCurrent);
  onlineManager.setOnline(false);
  let result!: Promise<unknown>;
  act(() => { result = hook.result.current.mutateAsync({ key: "staging/original", guard }).catch((error: unknown) => error); });
  await waitFor(() => expect(hook.result.current.isPaused).toBe(true));
  actionCurrent = false;
  await act(async () => { onlineManager.setOnline(true); await client.resumePausedMutations(); await result; });
  expect(net.calls).toHaveLength(0);
});
