import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cleanUploadSession, http, json, mountStaff, resetUploadSession, staffToken,
} from "../../../test/staffUploadHarness";
import { BatchLabels, type BatchDetail } from "./QrToolsBatch";

const historical = {
  id: 11, label_text: "Original A drill <snapshot>", target_type: "product",
  target_id: 41, qr_code: null,
};
const owned = {
  id: 12, label_text: "Original A unit label", target_type: "asset", target_id: 42,
  // The current same-maker target differs from the retained item snapshot.
  qr_code: { id: 73, payload: "owned-current-payload", target_type: "asset", target_id: 99 },
};
const svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>owned label</text></svg>';

function batch(items: BatchDetail["items"]): BatchDetail {
  return { id: 8, title: "Historical A batch", status: "draft", created_at: "2026-10-30T00:00:00Z", items };
}

function mount(items: BatchDetail["items"]) {
  return mountStaff(<BatchLabels batchId={8} batch={batch(items)} loading={false} error={null} />);
}

beforeEach(resetUploadSession);
afterEach(cleanUploadSession);

describe("BatchLabels batch-local nullable QR projection", () => {
  it("keeps the exact historical snapshot with no HTTP fetch for a null QR", async () => {
    const transport = http(() => { throw new Error("Null QR must never request an image"); });
    const view = mount([historical]);
    expect(screen.getByText("Original A drill <snapshot>")).toBeVisible();
    expect(screen.getByText("Product #41")).toBeVisible();
    expect(screen.getByText("QR unavailable")).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("0 printable of 1 QR labels collected")).toBeVisible();
    const button = screen.getByRole("button", { name: "Download available (ZIP)" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    // Flush React/query work before asserting the absence of dispatch.
    await act(async () => { await Promise.resolve(); });
    expect(view.client.isFetching()).toBe(0);
    expect(transport.fetch).not.toHaveBeenCalled();
  });

  it("prints only the allowed image in a partial batch and discloses available download", async () => {
    const transport = http(({ path }) => {
      if (path === "/admin/qr/73/print") return json({ payload: owned.qr_code.payload, svg });
      if (path === "/admin/qr-print-batches/8/download") {
        return new Response("synthetic ZIP bytes", {
          headers: { "Content-Type": "application/zip" },
        });
      }
      throw new Error(`Unexpected QR target request: ${path}`);
    });
    // Instrument only browser download leaves; keep the real mutation and bearer fetch.
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:owned-zip");
      static revokeObjectURL = vi.fn();
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    mount([historical, owned]);

    const image = await screen.findByRole("img", { name: "Original A unit label QR" });
    expect(image).toHaveAttribute("src", `data:image/svg+xml;base64,${btoa(svg)}`);
    const movedArticle = screen.getByText(historical.label_text).closest("article")!;
    expect(within(movedArticle).getByText("Product #41")).toBeVisible();
    expect(within(movedArticle).getByText("QR unavailable")).toBeVisible();
    expect(within(movedArticle).queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Asset #42")).toBeVisible();
    expect(screen.queryByText("Asset #99")).not.toBeInTheDocument();
    expect(screen.getByText("1 printable of 2 QR labels collected")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Download all (ZIP)" })).not.toBeInTheDocument();
    const download = screen.getByRole("button", { name: "Download available (ZIP)" });
    expect(download).toBeEnabled();
    fireEvent.click(download);
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(click.mock.instances[0]).toHaveAttribute("download", "qr-batch-8.zip");
    expect(click.mock.instances[0]).toHaveAttribute("href", "blob:owned-zip");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:owned-zip");
    expect(await screen.findByText("Download started")).toBeVisible();
    expect(transport.calls.map(({ path }) => path)).toEqual([
      "/admin/qr/73/print", "/admin/qr-print-batches/8/download",
    ]);
    for (const call of transport.calls) {
      expect(call.method).toBe("GET");
      expect(new Headers(call.init.headers).get("Authorization")).toBe(`Bearer ${staffToken()}`);
    }
  });

  it("disables an all-null batch, preserves each snapshot and dispatches no image requests", async () => {
    const transport = http(() => { throw new Error("All-null batch must never fetch"); });
    const second = { ...historical, id: 13, label_text: "Original moved A asset", target_type: "asset", target_id: 52 };
    const view = mount([historical, second]);
    expect(screen.getByText(historical.label_text)).toBeVisible();
    expect(screen.getByText(second.label_text)).toBeVisible();
    expect(screen.getByText("Product #41")).toBeVisible();
    expect(screen.getByText("Asset #52")).toBeVisible();
    expect(screen.getAllByText("QR unavailable")).toHaveLength(2);
    expect(screen.getByText("0 printable of 2 QR labels collected")).toBeVisible();
    const button = screen.getByRole("button", { name: "Download available (ZIP)" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    await act(async () => { await Promise.resolve(); });
    expect(view.client.isFetching()).toBe(0);
    expect(transport.fetch).not.toHaveBeenCalled();
  });

  it("disables an empty batch and never dispatches a print or download", async () => {
    const transport = http(() => { throw new Error("Empty batch must never fetch"); });
    const view = mount([]);
    expect(screen.getByText("No QR labels in this batch")).toBeVisible();
    expect(screen.getByText("0 QR labels collected")).toBeVisible();
    const button = screen.getByRole("button", { name: "Download all (ZIP)" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    await act(async () => { await Promise.resolve(); });
    expect(view.client.isFetching()).toBe(0);
    expect(transport.fetch).not.toHaveBeenCalled();
  });

  it("keeps the full-owned image and normal Download all control", async () => {
    const transport = http(({ path }) => {
      if (path === "/admin/qr/73/print") return json({ payload: owned.qr_code.payload, svg });
      throw new Error(`Unexpected print request: ${path}`);
    });
    mount([owned]);
    expect(await screen.findByRole("img", { name: `${owned.label_text} QR` })).toHaveAttribute(
      "src", `data:image/svg+xml;base64,${btoa(svg)}`,
    );
    expect(screen.getByText(owned.label_text)).toBeVisible();
    expect(screen.getByText("Asset #42")).toBeVisible();
    expect(screen.getByText("1 QR label collected")).toBeVisible();
    expect(screen.queryByText("QR unavailable")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download all (ZIP)" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Download available (ZIP)" })).not.toBeInTheDocument();
    expect(transport.calls.map(({ path }) => path)).toEqual(["/admin/qr/73/print"]);
    expect(new Headers(transport.calls[0].init.headers).get("Authorization")).toBe(`Bearer ${staffToken()}`);
  });
});
