import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { MemberAuthPanel } from "../features/members/MemberAuthPanel";
import { enter } from "./authOwnership";

export function mountMember() {
  const authenticated = vi.fn();
  const cancel = vi.fn();
  const panel = (slug: string) => <MemoryRouter initialEntries={["/m/A/member"]}>
    <MemberAuthPanel makerspaceSlug={slug} onAuthenticated={authenticated} onCancel={cancel} />
  </MemoryRouter>;
  const view = render(panel("A"));
  return { ...view, authenticated, cancel, visit: (slug: string) => view.rerender(panel(slug)) };
}
export function submitMember(signup = false) {
  if (signup) enter("Name", "Member A");
  enter("Email", "a@example.test");
  enter("Password", "private-password");
  fireEvent.submit(screen.getByRole("form", { name: signup ? "Create a member account" : "Member sign in" }));
}
export function chooseSignup() {
  fireEvent.click(screen.getByRole("button", { name: "Create a member account" }));
}
