import { fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));
vi.mock("../../lib/api", () => ({ publicV1Request }));

import { mountGoogleButton } from "./socialSdk";

describe("Google sign-in button sizing", () => {
  afterEach(() => {
    delete window.google;
    document.querySelectorAll('script[src="https://accounts.google.com/gsi/client"]').forEach((script) => script.remove());
  });

  it("fits a narrow sign-in card while retaining the desktop width cap", async () => {
    publicV1Request.mockResolvedValue({ nonce: "nonce" });
    const renderButton = vi.fn();
    window.google = { accounts: { id: { initialize: vi.fn(), renderButton } } };
    const host = document.createElement("div");
    Object.defineProperty(host, "clientWidth", { configurable: true, value: 228 });

    const mounted = mountGoogleButton(host, "client", "member", vi.fn(), vi.fn());
    await waitFor(() => expect(document.querySelector('script[src="https://accounts.google.com/gsi/client"]')).not.toBeNull());
    fireEvent.load(document.querySelector('script[src="https://accounts.google.com/gsi/client"]')!);
    await mounted;
    expect(renderButton).toHaveBeenLastCalledWith(host, expect.objectContaining({ width: 228 }));

    Object.defineProperty(host, "clientWidth", { configurable: true, value: 640 });
    await mountGoogleButton(host, "client", "member", vi.fn(), vi.fn());
    expect(renderButton).toHaveBeenLastCalledWith(host, expect.objectContaining({ width: 360 }));
  });
});
