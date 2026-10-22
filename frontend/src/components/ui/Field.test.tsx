import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Field } from "./Field";
import { Input, PasswordInput, SearchInput } from "./inputs";

describe("Field", () => {
  it("labels the control and links helper text through aria-describedby", () => {
    render(
      <Field label="Email" helperText="We send receipts here.">
        <Input type="email" />
      </Field>,
    );

    const input = screen.getByLabelText("Email");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)).toHaveTextContent("We send receipts here.");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("marks the control invalid and describes it with the error instead of the helper", () => {
    render(
      <Field label="Name" helperText="As on your ID." error="Enter your name.">
        <input />
      </Field>,
    );

    const input = screen.getByLabelText("Name");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const message = document.getElementById(input.getAttribute("aria-describedby")!);
    expect(message).toHaveTextContent("Enter your name.");
    expect(screen.queryByText("As on your ID.")).toBeNull();
  });

  it("keeps an existing aria-describedby and the control's own id", () => {
    render(
      <>
        <p id="extra">Extra context</p>
        <Field label="Code" hint="Six digits.">
          <input id="code-input" aria-describedby="extra" />
        </Field>
      </>,
    );

    const input = screen.getByLabelText("Code");
    expect(input.id).toBe("code-input");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toEqual(["extra", "code-input-description"]);
  });

  it("still labels composite content by wrapping it in the label", () => {
    render(
      <Field label="Quantity" hint="Whole units.">
        <div>
          <input type="number" />
        </div>
      </Field>,
    );

    expect(screen.getByRole("spinbutton", { name: /Quantity/ })).toBeInTheDocument();
  });
});

describe("PasswordInput", () => {
  it("toggles between hidden and visible text and says which state it is in", () => {
    render(
      <Field label="Password">
        <PasswordInput defaultValue="hunter2" />
      </Field>,
    );

    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("SearchInput", () => {
  it("shows a clear button only while there is a value", () => {
    const onClear = vi.fn();
    const { rerender } = render(<SearchInput aria-label="Search" value="" onChange={() => undefined} onClear={onClear} />);
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();

    rerender(<SearchInput aria-label="Search" value="drill" onChange={() => undefined} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});

describe("Button", () => {
  it("disables itself and reports busy while loading, keeping its name", () => {
    const onClick = vi.fn();
    render(<Button variant="primary" loading onClick={onClick}>Save</Button>);

    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>Cancel</Button>);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveAttribute("type", "button");
  });
});
