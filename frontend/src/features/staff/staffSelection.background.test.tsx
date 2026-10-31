import { act, screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import {
  calicut, deferred, json, kochi, listCalls, mountStaff, noPanel,
  panelIs, settle, transport,
} from "../../test/staffSelectionHarness";

it("preserves the mounted form during background access refresh and closes it when access is withdrawn", async () => {
  const { queryClient } = mountStaff("/m/kochi/admin/settings");
  await panelIs(kochi.id, "settings");
  const panel = screen.getByRole("region", { name: "Operational panel" });
  const refreshed = deferred<Response>();
  transport.routes.set("/admin/makerspaces", () => refreshed.promise);
  act(() => { void queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }); });
  await waitFor(() => expect(listCalls()).toHaveLength(2));
  expect(screen.getByRole("region", { name: "Operational panel" })).toBe(panel);
  await settle(refreshed, json([kochi, calicut]));
  expect(screen.getByRole("region", { name: "Operational panel" })).toBe(panel);

  const withdrawn = deferred<Response>();
  transport.routes.set("/admin/makerspaces", () => withdrawn.promise);
  act(() => { void queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }); });
  await waitFor(() => expect(listCalls()).toHaveLength(3));
  expect(screen.getByRole("region", { name: "Operational panel" })).toBe(panel);
  await settle(withdrawn, json([calicut]));
  await screen.findByRole("heading", { name: "Makerspace unavailable" });
  noPanel();
});
