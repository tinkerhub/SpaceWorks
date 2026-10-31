import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { tenantPublicRequest } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest,
}));

import { getSessionGeneration } from "../../lib/apiSession";
import { resetLendingSession } from "../../test/publicLendingHarness";
import { RegressionProviders, regressionClient } from "../../test/uiRegressionHarness";
import { BorrowRequestCard } from "./BorrowRequestCard";
import { PublicRequestPanel } from "./PublicRequestPanel";

const items = Array.from({ length: 35 }, (_, i) => ({
  productId: i + 1, name: `Selected equipment ${i + 1} with a long descriptive name`, quantity: 1,
}));

// Structural guard against the former desk/list scroll traps. jsdom does not measure CSS geometry.
function expectDocumentFlow(element: HTMLElement, boundary: HTMLElement) {
  let node: HTMLElement | null = element;
  while (node && node !== boundary) {
    const tokens = node.className.split(/\s+/);
    expect(tokens.filter((token) => /(?:^|:)(?:max-h-|overflow-y-(?:auto|scroll|hidden)|overflow-hidden|sticky$)/.test(token))).toEqual([]);
    node = node.parentElement;
  }
  expect(node).toBe(boundary);
}

beforeEach(() => { resetLendingSession(); tenantPublicRequest.mockReset(); });

describe("borrow desk document flow", () => {
  it("ordinary PublicRequestPanel keeps a long selection, contact fields, purpose, error and submit in document flow", async () => {
    tenantPublicRequest.mockRejectedValue(new Error("Please retry this request"));
    const client = regressionClient();
    // A settled anonymous session is a data fixture; the real session hook still determines eligibility.
    client.setQueryData(["public-request-session", "a", getSessionGeneration()], false);
    const onClear = vi.fn();
    const view = render(<RegressionProviders client={client}>
      <PublicRequestPanel items={items} makerspaceSlug="a" requestAccess="anyone" onClear={onClear} />
    </RegressionProviders>);
    expect(screen.getAllByRole("listitem")).toHaveLength(35);
    expect(screen.getByText(items[34].name)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Submit request" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Ada Contact" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Phone/), { target: { value: "+4412345" } });
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Community project" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Please retry this request");
    expect(submit).toBeEnabled();
    expect(tenantPublicRequest).toHaveBeenCalledTimes(1);
    expect(JSON.parse(tenantPublicRequest.mock.calls[0][2].body)).toMatchObject({
      contact_name: "Ada Contact", contact_email: "ada@example.com", contact_phone: "+4412345",
      requested_for: "Community project", items: items.map((item) => ({ product_id: item.productId, quantity: 1 })),
    });
    for (const element of [screen.getByRole("list"), screen.getByLabelText("Your name"), screen.getByLabelText("Email"),
      screen.getByLabelText(/^Phone/), screen.getByLabelText("Request purpose"), error, submit]) {
      expectDocumentFlow(element, view.container);
    }
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it("BorrowRequestCard preserves clear, edit, submit and token/status actions without a capped selected list", () => {
    const onClear = vi.fn();
    const onSubmit = vi.fn();
    const onRequestedForChange = vi.fn();
    const view = render(<RegressionProviders client={regressionClient()}>
      <BorrowRequestCard items={items} totalItems={35} requestedFor="Community project" identity="contact"
        contactName="Ada" contactEmail="ada@example.com" contactPhone="123" canSubmit submitPending={false}
        submitted submitError="Retry later" onClear={onClear} onSubmit={onSubmit} onRequestedForChange={onRequestedForChange}
        publicToken="borrow-reference" statusHref="/m/a/request-status" />
    </RegressionProviders>);
    expect(screen.getAllByRole("listitem")).toHaveLength(35);
    expect(screen.getByText(items[34].name)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check its status" })).toHaveAttribute("href", "/m/a/request-status?token=borrow-reference");
    expect(screen.getByText("borrow-reference")).toBeInTheDocument();
    for (const element of [screen.getByRole("list"), screen.getByLabelText("Your name"), screen.getByLabelText("Email"),
      screen.getByLabelText(/^Phone/), screen.getByLabelText("Request purpose"), screen.getByRole("alert"), screen.getByRole("button", { name: "Submit request" })]) {
      expectDocumentFlow(element, view.container);
    }
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Changed purpose" } });
    expect(onRequestedForChange).toHaveBeenCalledWith("Changed purpose");
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onClear).toHaveBeenCalledOnce();
  });
});
