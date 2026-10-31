import { accessToken } from "../test/accessTokens";
import { describe, expect, it } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, heldBody, oldData,
  publicationCases, publicationSetup, sessionChanges, successfulValue,
} from "./apiResponsePublicationTestHelpers";
import { getAccessToken, getSessionGeneration } from "./apiSession";
import { fetchMock, heldResponse, jsonResponse, requestHeaders } from "./apiSessionTestHelpers";

const expired = publicationSetup();
const retryCases = publicationCases.filter(({ retry }) => retry);
const tenantCases = publicationCases.filter(({ tenant }) => tenant);

describe.each(retryCases)("$name refresh publication", ({ request, kind }) => {
  it.each(sessionChanges)("does not dispatch a retry when refresh JSON becomes obsolete after $name", async (transition) => {
    const refresh = heldBody(200);
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(refresh.response);
    const rejection = expectSessionChanged(request());
    await refresh.entered;
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/auth\/refresh$/);
    await transition.change();
    refresh.resolve({ access: accessToken("obsolete-rotation") });
    await rejection;
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 3 : 2);
  });

  describe.each(["fetch", "body"] as const)("retried success held at %s", (boundary) => {
    it.each(sessionChanges)("does not publish the rotated session's data after $name", async (transition) => {
      const held = heldResponse();
      const body = heldBody(200, kind);
      fetchMock.mockResolvedValueOnce(jsonResponse(401))
        .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("rotated-A") }));
      if (boundary === "fetch") fetchMock.mockImplementationOnce(held.send);
      else fetchMock.mockResolvedValueOnce(body.response);
      const rejection = expectSessionChanged(request());
      await (boundary === "fetch" ? held.entered : body.entered);
      expect(getAccessToken()).toBe(accessToken("rotated-A"));
      expect(requestHeaders(2).get("Authorization")).toBe(`Bearer ${accessToken("rotated-A")}`);
      await transition.change();
      if (boundary === "fetch") held.resolve(jsonResponse(200, oldData));
      else body.resolve(successfulValue(kind));
      await rejection;
      expectUnchangedCredentials(transition.token, expired, transition.logout ? 4 : 3);
    });
  });

  it("keeps refresh in the original generation and decodes the current retry", async () => {
    const generation = getSessionGeneration();
    const body = heldBody(200, kind);
    const value = successfulValue(kind);
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("rotated-A") }))
      .mockResolvedValueOnce(body.response);
    const pending = request();
    await body.entered;
    expect(getSessionGeneration()).toBe(generation);
    body.resolve(value);
    await expect(pending).resolves.toBe(value);
    expectUnchangedCredentials(accessToken("rotated-A"), expired, 3);
    expect(requestHeaders(2).get("Authorization")).toBe(`Bearer ${accessToken("rotated-A")}`);
  });
});

describe.each(tenantCases)("$name unauthorized body retry guard", ({ request }) => {
  it.each(sessionChanges)("does not even start refresh after a stale 401 decode and $name", async (transition) => {
    const body = heldBody(401);
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(request());
    await body.entered;
    await transition.change();
    body.resolve({ detail: "Account A expired" });
    await rejection;
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });
});

describe.each(tenantCases)("$name anonymous fallback ownership", ({ request, kind }) => {
  it("adopts exactly its own clear and publishes the anonymous decoded response", async () => {
    const generation = getSessionGeneration();
    const body = heldBody(200, kind);
    const value = successfulValue(kind);
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(body.response);
    const pending = request();
    await body.entered;
    expect(getSessionGeneration()).toBe(generation + 1);
    expect(requestHeaders(2).get("Authorization")).toBeNull();
    expect(requestHeaders(2).get("X-Publishable-Key")).toBe("pk_forge");
    body.resolve(value);
    await expect(pending).resolves.toBe(value);
    expectUnchangedCredentials("", expired, 3);
  });

  describe.each(["fetch", "body"] as const)("anonymous response held at %s", (boundary) => {
    it.each(sessionChanges)("cannot adopt an external $name after its own clear", async (transition) => {
      const held = heldResponse();
      const body = heldBody(200, kind);
      fetchMock.mockResolvedValueOnce(jsonResponse(401))
        .mockResolvedValueOnce(jsonResponse(401));
      if (boundary === "fetch") fetchMock.mockImplementationOnce(held.send);
      else fetchMock.mockResolvedValueOnce(body.response);
      const rejection = expectSessionChanged(request());
      await (boundary === "fetch" ? held.entered : body.entered);
      expect(getAccessToken()).toBe("");
      expect(requestHeaders(2).get("Authorization")).toBeNull();
      await transition.change();
      if (boundary === "fetch") held.resolve(jsonResponse(200, oldData));
      else body.resolve(successfulValue(kind));
      await rejection;
      expectUnchangedCredentials(transition.token, expired, transition.logout ? 4 : 3);
    });
  });
});
