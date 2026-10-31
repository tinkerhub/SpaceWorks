import { vi } from "vitest";

export const PIN_KEY = "makerspace.session-intent";
export const LATCH_KEY = "makerspace.signed-out";
export const generation = "11111111-1111-4111-8111-111111111111";
export const nextGeneration = "22222222-2222-4222-8222-222222222222";
export const claimId = "33333333-3333-4333-8333-333333333333";
export const claimContext = {
  token_type: "claim_access", claim_session_id: claimId,
  claim_membership_id: 7, claim_makerspace_id: 9, absolute_expires_at: 4_102_444_800,
};

export function response(access?: string, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(access ? { access } : {}), {
    status, headers: { "Content-Type": "application/json" },
  });
}

/** A separate backing store models each tab's sessionStorage, including opener copies. */
export function tabStorage(copy?: Storage) {
  const values = new Map<string, string>();
  if (copy) for (let i = 0; i < copy.length; i += 1) {
    const key = copy.key(i)!;
    values.set(key, copy.getItem(key)!);
  }
  return {
    get length() { return values.size; },
    key: vi.fn((index: number) => [...values.keys()][index] ?? null),
    clear: vi.fn(() => { values.clear(); }),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, String(value)); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
  } satisfies Storage;
}

/** No static apiSession import: every simulated reload creates its real module owner. */
export async function reloadSession() {
  vi.resetModules();
  return await import("./apiSession");
}

export function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
