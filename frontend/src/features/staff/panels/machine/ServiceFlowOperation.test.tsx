import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { held, login, release } from "../../../../test/staffUploadHarness";
import { flowLifecycle, mountFlow } from "./serviceFlowTestHarness";
import { useServiceOperation } from "./useServiceOperation";

flowLifecycle();

function Operation({ scope = "A", dispatch, success }: {
  scope?: string;
  dispatch: (value: string) => Promise<unknown>;
  success: (value: string, isCurrent: () => boolean) => Promise<void>;
}) {
  const operation = useServiceOperation(scope, { dispatch, success, failure: () => undefined });
  return <>
    <button onClick={() => operation.submit(scope)}>Submit operation</button>
    <output aria-label="Pending">{String(operation.pending)}</output>
    <output aria-label="Can edit">{String(operation.canEdit())}</output>
  </>;
}

it("keeps a resolved dispatch pending and uneditable until its async success work settles", async () => {
  const successWork = held<void>();
  const dispatch = vi.fn(async () => ({ id: 4 }));
  const success = vi.fn(() => successWork.promise);
  const view = mountFlow(<Operation dispatch={dispatch} success={success} />);
  try {
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    await waitFor(() => {
      expect(success).toHaveBeenCalledTimes(1);
      expect(screen.getByLabelText("Pending")).toHaveTextContent("true");
    });
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("false");
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(view.client.getMutationCache().getAll()[0].state.status).toBe("pending");
    await release(successWork, undefined);
    await waitFor(() => expect(screen.getByLabelText("Pending")).toHaveTextContent("false"));
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("true");
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByLabelText("Pending")).toHaveTextContent("false"));
  } finally {
    await release(successWork, undefined);
  }
});

it.each(["scope", "session"] as const)("old async success finishing after a %s switch cannot unlock B's pending operation", async (change) => {
  const aSuccess = held<void>();
  const bDispatch = held<unknown>();
  const bSuccess = held<void>();
  let calls = 0;
  const dispatch = vi.fn(() => ++calls === 1 ? Promise.resolve({ id: 4 }) : bDispatch.promise);
  const success = vi.fn(() => calls === 1 ? aSuccess.promise : bSuccess.promise);
  const view = mountFlow(<Operation dispatch={dispatch} success={success} />);
  try {
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    await waitFor(() => expect(success).toHaveBeenCalledTimes(1));
    const aMutation = view.client.getMutationCache().getAll()[0];
    if (change === "session") login("B");
    view.rerender(<Operation scope={change === "scope" ? "B" : "A"} dispatch={dispatch} success={success} />);
    expect(screen.getByLabelText("Pending")).toHaveTextContent("false");
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("true");
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2));
    await release(aSuccess, undefined);
    await waitFor(() => expect(aMutation.state.status).toBe("success"));
    expect(screen.getByLabelText("Pending")).toHaveTextContent("true");
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("false");
    fireEvent.click(screen.getByRole("button", { name: "Submit operation" }));
    expect(dispatch).toHaveBeenCalledTimes(2);
    await release(bDispatch, { id: 5 });
    await waitFor(() => expect(success).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Pending")).toHaveTextContent("true");
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("false");
    await release(bSuccess, undefined);
    await waitFor(() => expect(screen.getByLabelText("Pending")).toHaveTextContent("false"));
    expect(screen.getByLabelText("Can edit")).toHaveTextContent("true");
  } finally {
    await release(aSuccess, undefined);
    await release(bDispatch, { id: 5 });
    await release(bSuccess, undefined);
  }
});
