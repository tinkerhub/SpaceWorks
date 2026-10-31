function base64url(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

/** Browser access fixture only; the signature is well formed, never a real secret. */
export function accessToken(label: string, overrides: Record<string, unknown> = {}): string {
  return [
    base64url({ alg: "HS256", typ: "JWT" }),
    base64url({
      token_type: "access", surface: "member", user_id: 1,
      auth_generation: "11111111-1111-4111-8111-111111111111",
      iat: 1_800_000_000, exp: 4_102_444_800,
      jti: "0123456789abcdef0123456789abcdef", label, ...overrides,
    }),
    base64url("test-signature-only"),
  ].join(".");
}
