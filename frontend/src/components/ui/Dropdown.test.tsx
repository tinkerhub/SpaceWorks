import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Dropdown } from "./Dropdown";
import { Field } from "./Field";

function SizeForm({ onChange }: { onChange?: (value: string) => void }) {
  return (
    <form aria-label="Order">
      <Field label="Size">
        <Dropdown name="size" defaultValue="m" onChange={(event) => onChange?.(event.target.value)}>
          <option value="s">Small</option>
          <option value="m">Medium</option>
          <option value="l">Large</option>
        </Dropdown>
      </Field>
    </form>
  );
}

function formValue(name: string) {
  return new FormData(screen.getByRole("form", { name: "Order" }) as HTMLFormElement).get(name);
}

describe("Dropdown", () => {
  it("posts its default value through the hidden native select", () => {
    render(<SizeForm />);

    expect(formValue("size")).toBe("m");
    expect(screen.getByRole("combobox", { name: "Size" })).toHaveTextContent("Medium");
  });

  it("updates the posted value and fires onChange when an option is picked", () => {
    const onChange = vi.fn();
    render(<SizeForm onChange={onChange} />);

    fireEvent.click(screen.getByRole("combobox", { name: "Size" }));
    fireEvent.click(screen.getByRole("option", { name: "Large" }));

    expect(onChange).toHaveBeenCalledWith("l");
    expect(formValue("size")).toBe("l");
    expect(screen.getByRole("combobox", { name: "Size" })).toHaveTextContent("Large");
  });

  it("follows a controlled value and supports an empty placeholder option", () => {
    function Controlled() {
      const [value, setValue] = useState("");
      return (
        <form aria-label="Order">
          <Dropdown name="colour" aria-label="Colour" value={value} onChange={(event) => setValue(event.target.value)}>
            <option value="" disabled>Choose a colour</option>
            <option value="red">Red</option>
          </Dropdown>
          <output>{value || "none"}</output>
        </form>
      );
    }
    render(<Controlled />);

    expect(formValue("colour")).toBe("");
    fireEvent.click(screen.getByRole("combobox", { name: "Colour" }));
    fireEvent.click(screen.getByRole("option", { name: "Red" }));

    expect(screen.getByText("red")).toBeInTheDocument();
    expect(formValue("colour")).toBe("red");
  });

  it("wires Field errors onto the visible trigger", () => {
    render(
      <Field label="Room" error="Pick a room.">
        <Dropdown name="room" defaultValue="">
          <option value="">None</option>
          <option value="a">Lab A</option>
        </Dropdown>
      </Field>,
    );

    const trigger = screen.getByRole("combobox", { name: "Room" });
    expect(trigger).toHaveAttribute("aria-invalid", "true");
    expect(document.getElementById(trigger.getAttribute("aria-describedby")!)).toHaveTextContent("Pick a room.");
  });
});
