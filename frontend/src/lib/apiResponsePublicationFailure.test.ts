import { accessToken } from "../test/accessTokens";
import { describe, expect, it } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, heldBody, publicationCases,
  publicationSetup, sessionChanges,
} from "./apiResponsePublicationTestHelpers";
import { deferred, fetchMock, jsonResponse } from "./apiSessionTestHelpers";

const expired = publicationSetup();

describe.each(publicationCases)("$name network failure ownership", ({ request }) => {
  it.each(sessionChanges)("rejects an obsolete transport failure after $name", async (transition) => {
    const entered = deferred<void>();
    const release = deferred<void>();
    fetchMock.mockImplementationOnce(async () => {
      entered.resolve();
      await release.promise;
      throw new TypeError("Account A connection failed");
    });
    const rejection = expectSessionChanged(request());
    await entered.promise;
    await transition.change();
    release.resolve();
    await rejection;
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });

  it("preserves a current transport failure without refresh or expiry", async () => {
    const failure = new TypeError("Offline");
    fetchMock.mockRejectedValueOnce(failure);
    await expect(request()).rejects.toBe(failure);
    expectUnchangedCredentials(accessToken("old-access"), expired, 1);
  });
});

describe.each(publicationCases)("$name successful-body decode failure ownership", ({ request, kind }) => {
  it.each(sessionChanges)("reports session_changed after $name instead of a late decode failure", async (transition) => {
    const body = heldBody(200, kind);
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(request());
    await body.entered;
    await transition.change();
    body.resolve(new SyntaxError("Old account body is invalid"));
    await rejection;
    expect(body.decode).toHaveBeenCalledTimes(1);
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });

  it("preserves the actual current decode failure", async () => {
    const body = heldBody(200, kind);
    const failure = new SyntaxError("Invalid body");
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expect(request()).rejects.toBe(failure);
    await body.entered;
    body.resolve(failure);
    await rejection;
    expectUnchangedCredentials(accessToken("old-access"), expired, 1);
  });
});

describe.each(publicationCases.filter(({ structured }) => structured))(
  "$name unreadable error body", ({ request }) => {
    it.each(sessionChanges)("does not turn a stale error decode failure after $name into a current error", async (transition) => {
      const body = heldBody(403);
      fetchMock.mockResolvedValueOnce(body.response);
      const rejection = expectSessionChanged(request());
      await body.entered;
      await transition.change();
      body.resolve(new SyntaxError("Invalid error JSON"));
      await rejection;
      expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
    });

    it("keeps a current unreadable error as the original HTTP status", async () => {
      const body = heldBody(403);
      fetchMock.mockResolvedValueOnce(body.response);
      const rejection = expect(request()).rejects.toMatchObject({ status: 403, body: {} });
      await body.entered;
      body.resolve(new SyntaxError("Invalid error JSON"));
      await rejection;
      expectUnchangedCredentials(accessToken("old-access"), expired, 1);
    });
  },
);

describe.each(publicationCases.filter(({ structured }) => !structured))(
  "$name public status compatibility", ({ request }) => {
    it("preserves the current simple status error without reading its body", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(404));
      await expect(request()).rejects.toThrow("Makerspace not found (404)");
      expectUnchangedCredentials(accessToken("old-access"), expired, 1);
    });
  },
);
