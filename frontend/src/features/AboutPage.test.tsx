import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteFooter } from "../components/SiteFooter";
import { RegressionProviders, regressionClient } from "../test/uiRegressionHarness";
import { AboutPage } from "./AboutPage";

function expectSafeExternal(link: HTMLElement, href: string) {
  expect(link).toHaveAttribute("href", href);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link.getAttribute("rel")?.split(/\s+/)).toEqual(expect.arrayContaining(["noopener", "noreferrer"]));
}

describe("About and public footer destinations", () => {
  it("routes usage to Labs, contribution to this fork, and both license links to the Labs AGPL", () => {
    render(<RegressionProviders client={regressionClient()} path="/about"><AboutPage /></RegressionProviders>);
    expectSafeExternal(screen.getByRole("link", { name: /Use SpaceWorks for your space/i }), "https://github.com/SpaceWorks-Labs/SpaceWorks");
    expectSafeExternal(screen.getByRole("link", { name: /Contribute to TinkerSpace's SpaceWorks/i }), "https://github.com/tinkerhub/SpaceWorks");
    expectSafeExternal(screen.getByRole("link", { name: /GNU Affero General Public License v3/i }), "https://github.com/SpaceWorks-Labs/SpaceWorks/blob/main/LICENSE");
    expectSafeExternal(within(screen.getByRole("contentinfo")).getByRole("link", { name: /License/i }), "https://github.com/SpaceWorks-Labs/SpaceWorks/blob/main/LICENSE");
    expect(screen.getByText(/Free to use, study, share and modify under the terms of the AGPL/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Browse makerspaces/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Staff login/i }).every((link) => link.getAttribute("href") === "/admin")).toBe(true);
  });

  it("standalone SiteFooter retains internal About/home navigation and the safe Labs license destination", () => {
    render(<RegressionProviders client={regressionClient()}><SiteFooter /></RegressionProviders>);
    const footer = within(screen.getByRole("contentinfo"));
    expect(footer.getByRole("link", { name: "About" })).toHaveAttribute("href", "/about");
    expect(footer.getByRole("link", { name: "Open makerspace listing" })).toHaveAttribute("href", "/");
    expectSafeExternal(footer.getByRole("link", { name: /License/i }), "https://github.com/SpaceWorks-Labs/SpaceWorks/blob/main/LICENSE");
  });
});
