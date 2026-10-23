import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { catalogPresentation } from "../../lib/catalogPresentation";
import type { Product } from "../../types/inventory";
import { ProductCard } from "./ProductCard";

const product = {
  id: 42,
  name: "Soldering iron",
  description: "Temperature-controlled station.",
  category_name: "Electronics",
  image_url: null,
  tracking_mode: "quantity",
  availability: { mode: "exact_count", label: "Available", count: 3 },
} as unknown as Product;

function renderCard(overrides: Partial<Product> = {}, quantity = 0) {
  const handlers = { onDecrement: vi.fn(), onIncrement: vi.fn(), onOpenDetails: vi.fn() };
  const view = render(<ProductCard product={{ ...product, ...overrides }} quantity={quantity} {...handlers} />);
  return { ...view, ...handlers };
}

describe("ProductCard", () => {
  it("renders a flat card with the name in sentence case and its availability", () => {
    const { container } = renderCard();
    const article = container.querySelector("article");
    expect(article).toHaveClass("border", "border-line", "rounded-lg");
    expect(container.querySelector(".border-2, .border-ink, .blueprint-band, .uppercase")).toBeNull();
    expect(screen.getByRole("heading", { name: "Soldering iron" })).toBeInTheDocument();
    expect(screen.getByText("3 available")).toBeInTheDocument();
    expect(screen.getByText("#0042")).toBeInTheDocument();
  });

  it("shows the platform item code when the item has one", () => {
    renderCard({ item_code: "TC-MCU-A" });
    expect(screen.getByText("TC-MCU-A")).toBeInTheDocument();
    expect(screen.queryByText("#0042")).toBeNull();
  });

  it("wires the stepper and details controls", () => {
    const { onIncrement, onDecrement, onOpenDetails } = renderCard({}, 1);
    fireEvent.click(screen.getByRole("button", { name: "Add Soldering iron" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Soldering iron" }));
    fireEvent.click(screen.getByRole("button", { name: "Open details for Soldering iron" }));
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(onIncrement).toHaveBeenCalledTimes(1);
    expect(onDecrement).toHaveBeenCalledTimes(1);
    expect(onOpenDetails).toHaveBeenCalledTimes(2);
  });

  it("disables adding an unavailable item and removing at zero", () => {
    renderCard({ availability: { mode: "status_only", label: "Unavailable" } as Product["availability"] });
    expect(screen.getByRole("button", { name: "Add Soldering iron" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Soldering iron" })).toBeDisabled();
  });
});

describe("catalogPresentation", () => {
  it("returns a stable tint and no tilt or hard shadow", () => {
    const first = catalogPresentation("forge");
    expect(first).toEqual(catalogPresentation("forge"));
    expect(Object.keys(first)).toEqual(["tint"]);
    expect(first.tint).not.toMatch(/shadow|tilt/);
  });
});
