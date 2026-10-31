import { describe, expect, it } from "vitest";
import { accessToken } from "../test/accessTokens";
import { parseSessionIntent, parseStoredSessionIntent, sameSessionIntent } from "./sessionIntent";
import { claimContext, claimId, generation, nextGeneration } from "./refreshPinTestHelpers";

const member = { version: 1, token_type: "access", surface: "member", user_id: "1", auth_generation: generation };
const claim = { ...member, token_type: "claim_access", claim_session_id: claimId,
  claim_membership_id: "7", claim_makerspace_id: "9" };

function rawPayload(value: unknown) {
  const [header, , signature] = accessToken("template").split(".");
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const encoded = btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${encoded}.${signature}`;
}

describe("browser session identity tuples", () => {
  it.each([
    { name: "member", overrides: {}, expected: member },
    { name: "platform staff", overrides: { surface: "staff", staff_scope: "platform" },
      expected: { ...member, surface: "staff", staff_scope: "platform" } },
    { name: "tenant staff", overrides: { surface: "staff", staff_scope: "9" },
      expected: { ...member, surface: "staff", staff_scope: "9" } },
    { name: "API staff", overrides: { surface: "staff_api" }, expected: { ...member, surface: "staff_api" } },
    { name: "verification", overrides: { surface: "verification_only" }, expected: { ...member, surface: "verification_only" } },
    { name: "claim member", overrides: claimContext, expected: claim },
  ])("accepts $name with only its canonical immutable fields", ({ overrides, expected }) => {
    const intent = parseSessionIntent(accessToken("supported", overrides));
    expect(intent).toEqual(expected);
    expect(Object.isFrozen(intent)).toBe(true);
    expect(parseStoredSessionIntent(JSON.stringify(intent))).toEqual(expected);
  });

  it("canonicalizes safe user IDs and UUID case while ignoring rotating and private claims", () => {
    const original = parseSessionIntent(accessToken("first", { user_id: "1" }))!;
    const rotated = parseSessionIntent(accessToken("second", {
      jti: "different", iat: 1, exp: 2,
      email: "member@example.test", username: "Private name",
    }))!;
    expect(rotated).toEqual(member);
    expect(sameSessionIntent(original, rotated)).toBe(true);
    expect(parseSessionIntent(accessToken("max-safe", { user_id: Number.MAX_SAFE_INTEGER })))
      .toEqual({ ...member, user_id: String(Number.MAX_SAFE_INTEGER) });
    const mixedCase = "ABCDEF12-ABCD-4ABC-8ABC-ABCDEF123456";
    expect(parseSessionIntent(accessToken("UUID case", { auth_generation: mixedCase })))
      .toEqual({ ...member, auth_generation: mixedCase.toLowerCase() });
  });

  it.each([
    { name: "missing generation", overrides: { auth_generation: undefined } },
    { name: "non-UUID generation", overrides: { auth_generation: "generation-A" } },
    { name: "missing surface", overrides: { surface: undefined } },
    { name: "unknown surface", overrides: { surface: "native" } },
    { name: "refresh token", overrides: { token_type: "refresh" } },
    { name: "native grant", overrides: { device_grant_id: claimId } },
    { name: "native family even null", overrides: { device_family_id: null } },
    { name: "zero user", overrides: { user_id: 0 } },
    { name: "negative user", overrides: { user_id: -1 } },
    { name: "fractional user", overrides: { user_id: 1.5 } },
    { name: "unsafe user", overrides: { user_id: Number.MAX_SAFE_INTEGER + 1 } },
    { name: "noncanonical user", overrides: { user_id: "01" } },
    { name: "exponential user", overrides: { user_id: "1e2" } },
    { name: "boolean user", overrides: { user_id: true } },
    { name: "missing staff scope", overrides: { surface: "staff" } },
    { name: "numeric staff scope", overrides: { surface: "staff", staff_scope: 9 } },
    { name: "noncanonical staff scope", overrides: { surface: "staff", staff_scope: "09" } },
    { name: "zero staff scope", overrides: { surface: "staff", staff_scope: "0" } },
    { name: "member scope", overrides: { staff_scope: "platform" } },
    { name: "staff API scope", overrides: { surface: "staff_api", staff_scope: "platform" } },
    { name: "partial normal claim", overrides: { claim_membership_id: 7 } },
    { name: "claim type without context", overrides: { token_type: "claim_access" } },
    { name: "claim missing membership", overrides: { ...claimContext, claim_membership_id: undefined } },
    { name: "claim invalid session", overrides: { ...claimContext, claim_session_id: "bad" } },
    { name: "claim invalid makerspace", overrides: { ...claimContext, claim_makerspace_id: -1 } },
    { name: "claim staff surface", overrides: { ...claimContext, surface: "staff", staff_scope: "9" } },
    { name: "claim extraneous scope", overrides: { ...claimContext, staff_scope: "9" } },
    { name: "native absolute lifetime", overrides: { absolute_expires_at: 4_102_444_800 } },
  ])("rejects $name", ({ overrides }) => {
    expect(parseSessionIntent(accessToken("invalid", overrides))).toBeNull();
  });

  it.each([
    undefined, null, 1, "", "opaque", "e30.e30", "e30.e30.e30.e30", "e30..e30",
    "e30.e30=.e30", "e30.e30.$bad", "e30.a.e30", "e30.____.e30",
    rawPayload([]), rawPayload(null), rawPayload("claims"), "e30.bm90LWpzb24.e30",
    // e31 decodes like e30 but contains noncanonical trailing bits.
    "e30.e31.e30", accessToken("x".repeat(9_000)),
    `${"a".repeat(16_384)}.${accessToken("small").split(".")[1]}.e30`,
  ])("rejects malformed or unbounded compact input %#", (token) => {
    expect(parseSessionIntent(token)).toBeNull();
  });

  it("decodes bounded UTF-8 claims without storing their text", () => {
    expect(parseSessionIntent(accessToken("é工具".repeat(500)))).toEqual(member);
  });

  it.each([
    { version: 2 }, { email: "private@example.test" }, { access: accessToken("secret") },
    { jti: "rotating" }, { user_id: 1 }, { user_id: "01" },
    { staff_scope: null }, { auth_generation: undefined },
  ])("rejects stored schema drift %#", (change) => {
    expect(parseStoredSessionIntent(JSON.stringify({ ...member, ...change }))).toBeNull();
  });

  it.each([null, "", "{", "[]", "null", JSON.stringify({ ...member, padding: "x".repeat(1_024) })])(
    "rejects malformed or oversized stored pins %#", (raw) => {
      expect(parseStoredSessionIntent(raw)).toBeNull();
    },
  );

  it.each([
    { user_id: 2 }, { auth_generation: nextGeneration }, { surface: "verification_only" },
    { surface: "staff", staff_scope: "platform" }, claimContext,
  ])("distinguishes an immutable context change %#", (overrides) => {
    expect(sameSessionIntent(parseSessionIntent(accessToken("A"))!,
      parseSessionIntent(accessToken("B", overrides))!)).toBe(false);
  });
});
