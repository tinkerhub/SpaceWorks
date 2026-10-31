export type RequestKind = "hardware" | "machine";
export type RequestCapability = { kind: RequestKind; token: string; saved_at: number };
export type CapabilityOutcome = { saved: boolean; records: RequestCapability[]; warning?: string };
const LIMIT = 50;
const MAX_BYTES = 64_000;
const warning = "This browser could not verify the saved links. Keep your private reference or link somewhere safe.";
const registryKey = (slug: string) => `spaceworks.requests.${slug}`;
const legacyKeys = (slug: string) => [`tinkerspace.serviceStatus.${slug}`, `tinkerspace.printStatus.${slug}`];

// Tokens are opaque capabilities, including older non-UUID references. Never treat them as URLs.
export function validRequestToken(token: unknown): token is string {
  if (typeof token !== "string" || token.length === 0 || token.length > 512
    || token !== token.trim() || /[\u0000-\u001f\u007f-\u009f]/u.test(token)) return false;
  try { encodeURIComponent(token); return true; } catch { return false; }
}
function normalize(records: RequestCapability[]) {
  const unique = new Map<string, RequestCapability>();
  for (const record of records.sort((a, b) => a.saved_at - b.saved_at)) {
    unique.set(JSON.stringify([record.kind, record.token]), record);
  }
  return [...unique.values()].sort((a, b) => b.saved_at - a.saved_at).slice(0, LIMIT);
}
// Keep newly admitted links reachable even when older saved timestamps are in the future.
function includeAdmitted(records: RequestCapability[], admitted: RequestCapability[]) {
  const first = normalize(admitted);
  const keys = new Set(first.map((row) => JSON.stringify([row.kind, row.token])));
  const remaining = records.filter((row) => !keys.has(JSON.stringify([row.kind, row.token])));
  return normalize([...first, ...remaining].slice(0, LIMIT));
}
function read(slug: string): RequestCapability[] {
  const raw = localStorage.getItem(registryKey(slug));
  if (raw === null) return [];
  if (raw.length > MAX_BYTES) throw new Error("Saved links are too large.");
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length > LIMIT) throw new Error("Invalid saved links.");
  const records: RequestCapability[] = [];
  for (const item of parsed) {
    if (!item || typeof item !== "object" || (item.kind !== "hardware" && item.kind !== "machine")
      || !validRequestToken(item.token) || !Number.isSafeInteger(item.saved_at) || item.saved_at < 0) {
      throw new Error("Invalid saved link.");
    }
    records.push({ kind: item.kind, token: item.token, saved_at: item.saved_at });
  }
  return normalize(records);
}
function writeVerified(slug: string, records: RequestCapability[]) {
  const encoded = JSON.stringify(records);
  localStorage.setItem(registryKey(slug), encoded);
  if (localStorage.getItem(registryKey(slug)) !== encoded) throw new Error("Saved links were not persisted.");
}
function removeVerified(key: string) {
  localStorage.removeItem(key);
  if (localStorage.getItem(key) !== null) throw new Error("Link was not forgotten.");
}

/** Called only after a submission's owner has admitted its successful response. Never throws. */
export function saveRequestCapability(slug: string, kind: RequestKind, token: string): CapabilityOutcome {
  let records: RequestCapability[] = [];
  try {
    if (!slug || !validRequestToken(token)) return { saved: false, records, warning };
    if (kind === "machine") {
      // Preserve the existing last-token compatibility key; only explicit reveal reads it.
      try { localStorage.setItem(legacyKeys(slug)[0], token); } catch { /* Registry verification below decides the outcome. */ }
    }
    records = includeAdmitted(read(slug), [{ kind, token, saved_at: Date.now() }]);
    writeVerified(slug, records);
    return { saved: true, records };
  } catch {
    return { saved: false, records, warning };
  }
}

/** Explicit reveal is the only reader/migrator of saved and legacy capabilities. */
export function revealRequestCapabilities(slug: string): CapabilityOutcome {
  let records: RequestCapability[] = [];
  const legacy: { key: string; token: string }[] = [];
  let failed = false;
  try { records = read(slug); } catch { failed = true; }
  for (const key of legacyKeys(slug)) {
    try {
      const token = localStorage.getItem(key)?.trim();
      if (validRequestToken(token)) legacy.push({ key, token });
    } catch { failed = true; }
  }
  records = includeAdmitted(records, legacy.map(({ token }) => ({ kind: "machine" as const, token, saved_at: Date.now() })));
  try {
    // Never overwrite unreadable data. Even on failure the explicitly revealed legacy link is usable.
    if (failed) return { saved: false, records, warning };
    if (legacy.length) {
      writeVerified(slug, records);
      for (const { key, token } of legacy) {
        // Retire only links included in the verified bounded registry.
        if (records.some((row) => row.kind === "machine" && row.token === token)) removeVerified(key);
      }
    }
    return { saved: true, records };
  } catch { return { saved: false, records, warning }; }
}

/** Local-only deletion. A failed legacy removal cannot be reported as successful forgetting. */
export function forgetRequestCapabilities(slug: string, target?: RequestCapability): CapabilityOutcome {
  let records: RequestCapability[] = [];
  try {
    if (!target) {
      for (const key of [...legacyKeys(slug), registryKey(slug)]) removeVerified(key);
      return { saved: true, records };
    }
    records = read(slug);
    for (const key of legacyKeys(slug)) {
      const token = localStorage.getItem(key)?.trim();
      if (target.kind === "machine" && token === target.token) removeVerified(key);
    }
    records = records.filter((row) => !(row.kind === target.kind && row.token === target.token));
    writeVerified(slug, records);
    return { saved: true, records };
  } catch {
    return { saved: false, records, warning: "This browser could not verify that the link was forgotten. It may appear again on this browser." };
  }
}
