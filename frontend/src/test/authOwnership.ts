import { accessToken } from "./accessTokens";
import { fireEvent, screen } from "@testing-library/react";
import { clearAccessToken, logout, setAccessToken } from "../lib/apiSession";

export function held<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

export const epochChanges = ["clear", "logout", "new login", "same-token login"] as const;
export async function changeEpoch(kind: typeof epochChanges[number]) {
  if (kind === "logout") await logout();
  else if (kind === "clear") clearAccessToken();
  else setAccessToken(kind === "same-token login" ? accessToken("account-A") : accessToken("account-B", { user_id: 2 }));
}

export function enter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
