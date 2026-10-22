import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmailTemplateTypeSelector } from "./EmailTemplateTypeSelector";

describe("EmailTemplateTypeSelector", () => {
  it("renders nothing when no machine type can override the template", () => {
    const { container } = render(<EmailTemplateTypeSelector canEditSpaceDefault types={[]} selectedTypeId={null} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Machine type")).toBeNull();
  });

  it("offers the space default beside each overridable type", () => {
    render(
      <EmailTemplateTypeSelector
        canEditSpaceDefault
        types={[{ id: 3, name: "Laser cutter", is_active: true, is_overridden: false }]}
        selectedTypeId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("group", { name: "Machine type" })).toBeTruthy();
    expect(screen.getByText("Space default")).toBeTruthy();
    expect(screen.getByText("Laser cutter")).toBeTruthy();
  });
});
