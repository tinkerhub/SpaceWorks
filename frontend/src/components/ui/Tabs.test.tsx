import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NavTabs, Tabs, TabsContent, TabsList, TabsTrigger } from "./Tabs";

function renderTabs() {
  return render(
    <Tabs defaultValue="loans">
      <TabsList aria-label="Member sections">
        <TabsTrigger value="loans">Loans</TabsTrigger>
        <TabsTrigger value="prints">Prints</TabsTrigger>
        <TabsTrigger value="events">Events</TabsTrigger>
      </TabsList>
      <TabsContent value="loans">Loan list</TabsContent>
      <TabsContent value="prints">Print list</TabsContent>
      <TabsContent value="events">Event list</TabsContent>
    </Tabs>,
  );
}

describe("Tabs", () => {
  it("exposes a named tablist with one selected tab tied to its panel", () => {
    renderTabs();

    expect(screen.getByRole("tablist", { name: "Member sections" })).toBeInTheDocument();
    const loans = screen.getByRole("tab", { name: "Loans" });
    expect(loans).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Prints" })).toHaveAttribute("aria-selected", "false");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Loan list");
    expect(loans.getAttribute("aria-controls")).toBe(panel.id);
  });

  it("moves selection with the arrow keys and wraps around", async () => {
    renderTabs();
    const loans = screen.getByRole("tab", { name: "Loans" });
    loans.focus();

    fireEvent.keyDown(loans, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Prints" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Print list");

    fireEvent.keyDown(screen.getByRole("tab", { name: "Prints" }), { key: "End" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Events" })).toHaveFocus());

    fireEvent.keyDown(screen.getByRole("tab", { name: "Events" }), { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Loans" })).toHaveAttribute("aria-selected", "true"));
  });

  it("keeps a single tab stop that lands on the selected tab", async () => {
    renderTabs();

    act(() => screen.getByRole("tablist").focus());

    await waitFor(() => expect(screen.getByRole("tab", { name: "Loans" })).toHaveFocus());
    const tabStops = screen.getAllByRole("tab").filter((tab) => tab.getAttribute("tabindex") === "0");
    expect(tabStops).toEqual([screen.getByRole("tab", { name: "Loans" })]);
  });
});

describe("NavTabs", () => {
  it("marks the tab for the current route with aria-current", () => {
    render(
      <MemoryRouter initialEntries={["/admin/stock"]}>
        <NavTabs
          label="Inventory views"
          items={[
            { to: "/admin/items", label: "Items" },
            { to: "/admin/stock", label: "Stock" },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("navigation", { name: "Inventory views" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stock" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Items" })).not.toHaveAttribute("aria-current");
  });
});
