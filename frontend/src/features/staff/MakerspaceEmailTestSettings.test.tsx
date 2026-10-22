import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import { ToastProvider } from "../../components/ui";
import { MakerspaceEmailTestSettings } from "./MakerspaceEmailTestSettings";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("send test email", () => {
  it("sends to the signed-in staffer and confirms with a toast", async () => {
    staffRequest.mockResolvedValue({ delivered: true, to: "manager@lab.test", email_log_id: 3 });
    wrap(<MakerspaceEmailTestSettings makerspaceId={7} unsaved={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Send test email" }));

    expect(await screen.findByText("Test email sent to manager@lab.test")).toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/email-test", { method: "POST" });
  });

  it("names the problem when the email is not sent", async () => {
    staffRequest.mockResolvedValue({
      delivered: false, to: "manager@lab.test", email_log_id: 4,
      detail: "The mail server rejected the SMTP username or password.",
    });
    wrap(<MakerspaceEmailTestSettings makerspaceId={7} unsaved={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Send test email" }));

    // Once in the toast, once in the inline result under the button.
    expect(await screen.findAllByText("The mail server rejected the SMTP username or password.")).toHaveLength(2);
    expect(screen.getByText("Not sent")).toBeInTheDocument();
  });

  it("waits for unsaved settings to be saved", () => {
    wrap(<MakerspaceEmailTestSettings makerspaceId={7} unsaved />);

    expect(screen.getByRole("button", { name: "Send test email" })).toBeDisabled();
    expect(screen.getByText("Save your changes before sending a test email.")).toBeInTheDocument();
  });
});
