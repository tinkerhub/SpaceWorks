import { accessToken } from "./accessTokens";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import type { StaffAuthUser } from "../lib/api";
import { OrganizationInvitationRedeemPage } from "../features/organizations/OrganizationInvitationRedeemPage";
import { enter } from "./authOwnership";

export const invitationMember = { username: "canonical-A", email_verified: true, role: "member", is_superuser: false,
  must_change_password: false, makerspaces: [] } satisfies StaffAuthUser;
export const invitationLogin = { access: accessToken("member-A"), surface: "member", user: invitationMember };
export const invitationRedeemed = { membership: { id: 7, organization_id: 3 }, user: invitationMember };
function Visits() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return <><output aria-label="Committed invitation route">{pathname}</output>
    <button onClick={() => navigate("/invitations/A")}>Visit A</button>
    <button onClick={() => navigate("/invitations/B")}>Visit B</button></>;
}
export function mountInvitation({ strict = false }: { strict?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["private"], { owner: "A" });
  const clear = vi.spyOn(client, "clear");
  const app = <QueryClientProvider client={client}><MemoryRouter initialEntries={["/invitations/A"]} useTransitions={false}>
    <Visits /><Routes>
      <Route path="/invitations/:token" element={<OrganizationInvitationRedeemPage />} />
      <Route path="/admin" element={<h1>Staff destination</h1>} />
    </Routes>
  </MemoryRouter></QueryClientProvider>;
  const view = render(strict ? <StrictMode>{app}</StrictMode> : app);
  return { ...view, client, clear, visit: (token: "A" | "B") => fireEvent.click(screen.getByRole("button", { name: `Visit ${token}` })) };
}
export async function signIntoInvitation(staff = false) {
  await screen.findByLabelText("Username or email");
  enter("Username or email", "typed-A@example.test");
  enter("Password", staff ? "staff-secret" : "member-secret");
  fireEvent.submit(screen.getByLabelText("Password").closest("form")!);
}
