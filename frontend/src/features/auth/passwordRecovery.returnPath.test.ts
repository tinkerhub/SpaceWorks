import { describe, expect, it } from "vitest";

import { signInPath } from "./passwordRecovery";

const TRUSTED = "https://trusted.example";
const queryFor = (next: string) => `?${new URLSearchParams({ next })}`;

describe("recovery sign-in return paths", () => {
  it.each([
    ["LF between slashes", "/\n/attacker.example"],
    ["CR between slashes", "/\r/attacker.example"],
    ["tab between slashes", "/\t/attacker.example"],
    ["NUL", "/member\u0000"],
    ["DEL", "/member\u007f"],
    ["embedded space", "/member area"],
    ["leading space", " /member"],
    ["backslash authority", "/\\attacker.example"],
    ["internal backslash", "/m\\forge/member"],
    ["protocol relative", "//attacker.example/member"],
    ["absolute HTTPS", "https://attacker.example/member"],
    ["absolute trusted URL", "https://trusted.example/member"],
    ["relative path", "member"],
    ["script scheme", "javascript:alert(1)"],
    ["empty value", ""],
  ])("falls back for %s supplied as an encoded URLSearchParams value", (_name, next) => {
    const result = signInPath(queryFor(next));
    expect(result).toBe("/admin");
    expect(new URL(result, TRUSTED).origin).toBe(TRUSTED);
  });

  it.each([
    "?next=%2F%0A%2Fattacker.example",
    "?next=%2F%0D%2Fattacker.example",
    "?next=%2F%09%2Fattacker.example",
    "?next=%2F%5Cattacker.example",
    "?next=%2Fmember%00",
    "?next=%2Fmember%7F",
    "?next=%2Fmember+area",
    "?next=https%3A%2F%2Fattacker.example",
    "",
  ])("rejects the decoded attack or missing next in %j", (query) => {
    const result = signInPath(query);
    expect(result).toBe("/admin");
    expect(new URL(result, TRUSTED).origin).toBe(TRUSTED);
  });

  it.each([
    "/", "/admin", "/member", "/m/forge/member",
    "/member?tab=loans&sort=latest#active",
    "/m/forge/member?next=%2Ftools#requests",
    "/member?label=two%20words#safe",
  ])("preserves safe internal path %s exactly", (next) => {
    const result = signInPath(queryFor(next));
    expect(result).toBe(next);
    expect(new URL(result, TRUSTED).origin).toBe(TRUSTED);
  });

  it("blocks a prefix-passing path that WHATWG control normalization resolves off-site", () => {
    const attack = "/\n/attacker.example";
    // The old root-relative prefix check alone accepts this string.
    expect(/^\/(?![/\\])/.test(attack)).toBe(true);
    expect(new URL(attack, TRUSTED).origin).toBe("https://attacker.example");
    const result = signInPath(queryFor(attack));
    expect(result).toBe("/admin");
    expect(new URL(result, TRUSTED).origin).toBe(TRUSTED);
  });
});
