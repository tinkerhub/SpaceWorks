import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { expect, onTestFinished, vi } from "vitest";

import { ToastProvider } from "../components/ui";
import { NeedsFixShelf } from "../features/staff/panels/NeedsFixShelf";
import type { InventoryAssetRow } from "../features/staff/panels/inventoryForm";
import type { Makerspace } from "../features/staff/panels/shared";
import { staffRequest } from "../lib/api";

type ShelfItem = {
  id: number;
  name: string;
  tracking_mode: "quantity" | "individual";
  needs_fix_quantity: number;
  available_quantity: number;
  total_quantity: number;
};

export const space: Makerspace = {
  id: 17, name: "Workshop", slug: "workshop", public_code: "WORK",
  telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
  enabled_modules: ["asset_units", "containers"],
};
export const individualItem: ShelfItem = {
  id: 73, name: "Tagged drill", tracking_mode: "individual",
  needs_fix_quantity: 1, available_quantity: 0, total_quantity: 1,
};
export const quantityItem: ShelfItem = {
  id: 84, name: "Clamps", tracking_mode: "quantity",
  needs_fix_quantity: 5, available_quantity: 3, total_quantity: 8,
};
export const maintenanceAsset: InventoryAssetRow = {
  id: 901, asset_tag: "DRILL-901", serial_number: "", status: "maintenance",
  box: null, box_label: null, qr_code_id: null, qr_payload: null,
  notes: "", public_self_checkout_enabled: false,
};

export const paths = {
  shelf: `/admin/inventory/needs-fix?makerspace=${space.id}`,
  assets: `/admin/inventory/${individualItem.id}/assets`,
  containers: `/admin/makerspace/${space.id}/containers?page_size=1000`,
  unitRepair: `/admin/assets/${maintenanceAsset.id}/fix-status`,
  quantityAction: `/admin/inventory/${quantityItem.id}/needs-fix`,
};

// Keep the hooks, components and invalidation real; this is only the HTTP boundary.
// Snapshots matter: a fake server update must reach React through a real refetch.
export function renderShelf({ items = [quantityItem], modules = space.enabled_modules }: {
  items?: ShelfItem[];
  modules?: string[];
} = {}) {
  let rows = items.map((item) => ({ ...item }));
  let asset = { ...maintenanceAsset };
  const reads: Record<string, number> = {};
  const writes: { path: string; method: string; body: string | undefined }[] = [];
  const unexpected: string[] = [];
  const request = vi.mocked(staffRequest);
  request.mockReset();
  request.mockImplementation(async (path, options) => {
    const method = options?.method ?? "GET";
    if (method === "GET") {
      reads[path] = (reads[path] ?? 0) + 1;
      if (path === paths.shelf) return {
        results: rows.filter((row) => row.needs_fix_quantity > 0).map((row) => ({ ...row })),
      };
      if (path === paths.assets) return { results: [{ ...asset }] };
      if (path === paths.containers) return { results: [] };
    } else {
      const body = options?.body as string | undefined;
      writes.push({ path, method, body });
      if (method === "POST" && path === paths.unitRepair) {
        asset = { ...asset, status: "available" };
        rows = rows.map((row) => row.id === individualItem.id
          ? { ...row, needs_fix_quantity: 0, available_quantity: 1 } : row);
        return { ...asset };
      }
      if (method === "POST" && path === paths.quantityAction) {
        const { action, quantity } = JSON.parse(body ?? "{}");
        rows = rows.map((row) => row.id === quantityItem.id ? {
          ...row,
          needs_fix_quantity: row.needs_fix_quantity - quantity,
          available_quantity: row.available_quantity + (action === "repair" ? quantity : 0),
          total_quantity: row.total_quantity - (action === "scrap" ? quantity : 0),
        } : row);
        return { ...rows.find((row) => row.id === quantityItem.id) };
      }
    }
    unexpected.push(`${method} ${path}`);
    throw new Error(`Unexpected staff request: ${method} ${path}`);
  });

  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, gcTime: Infinity }, mutations: { retry: false },
  } });
  const inventoryKeys = [
    ["inventory", space.id], ["public-inventory", space.slug], ["public-stats", space.slug],
  ];
  for (const key of inventoryKeys) client.setQueryData(key, { cached: true });
  const tree = (enabled_modules: string[] | undefined) => (
    <QueryClientProvider client={client}>
      <ToastProvider><NeedsFixShelf makerspace={{ ...space, enabled_modules }} /></ToastProvider>
    </QueryClientProvider>
  );
  const view = render(tree(modules));
  onTestFinished(() => {
    view.unmount();
    client.clear();
    expect(unexpected).toEqual([]);
  });
  return {
    client, reads, writes, inventoryKeys, request,
    setModules: (next: string[]) => view.rerender(tree(next)),
  };
}
