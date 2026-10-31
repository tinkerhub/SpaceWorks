import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { platformMounts } from "../../test/platformPanelMocks";
import { accessToken } from "../../test/accessTokens";
import {
  client, deferred, json, mountStaff, noPanel, platformStaff, settle, transport,
} from "../../test/staffSelectionHarness";

beforeEach(() => { platformMounts.length = 0; transport.user = platformStaff(); });

describe("Platform respects the password and recovery gates", () => {
  it("waits for a fresh identity after password rotation before exposing global controls", async () => {
    transport.user = platformStaff({ must_change_password: true });
    const identity = deferred<Response>();
    transport.routes.set("/auth/change-password", () => {
      transport.routes.set("/auth/me", () => identity.promise.then((response) => response.clone()));
      return json({ detail: "Password updated", access: accessToken("rotated-password", {
        surface: "staff", staff_scope: "platform", auth_generation: "22222222-2222-4222-8222-222222222222",
      }) });
    });
    mountStaff("/admin/platform");
    await screen.findByRole("heading", { name: "Set a new password" });
    expect(platformMounts).toEqual([]);
    for (const [label, value] of [["Current password", "old-password"], ["New password", "new-password"], ["Confirm new password", "new-password"]]) {
      fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    await waitFor(() => expect(transport.calls.filter(({ path }) => path === "/auth/me").length).toBeGreaterThan(1));
    noPanel();
    expect(platformMounts).toEqual([]);
    await settle(identity, json(platformStaff()));
    expect(await screen.findByRole("region", { name: "Platform email leaf" })).toBeVisible();
  });

  it("keeps global forms behind recovery quarantine until the acknowledgement succeeds", async () => {
    const queryClient = client();
    const quarantine = { mode: "quarantined", quarantine_reason: "Restore requires review", residual_risk: "External credentials need review", quarantined_at: null };
    queryClient.setQueryData(["deployment-recovery-state"], quarantine);
    transport.routes.set("/recovery", (init) => json(init.method === "POST" ? { ...quarantine, mode: "normal" } : quarantine));
    mountStaff("/admin/platform", { queryClient });
    await screen.findByRole("heading", { name: "Authority is suspended" });
    expect(platformMounts).toEqual([]);
    expect(screen.getByRole("button", { name: "Lift quarantine" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed the restore report/ }));
    fireEvent.click(screen.getByRole("button", { name: "Lift quarantine" }));
    expect(await screen.findByRole("region", { name: "Platform email leaf" })).toBeVisible();
    const acknowledgement = transport.calls.find(({ path, init }) => path === "/recovery" && init.method === "POST");
    expect(JSON.parse(String(acknowledgement?.init.body))).toEqual({ acknowledgement: quarantine.residual_risk });
  });
});
