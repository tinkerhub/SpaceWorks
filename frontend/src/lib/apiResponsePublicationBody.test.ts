import { accessToken } from "../test/accessTokens";
import { describe, expect, it } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, heldBody, oldData,
  publicationCases, publicationSetup, sessionChanges, successfulValue,
} from "./apiResponsePublicationTestHelpers";
import { fetchMock } from "./apiSessionTestHelpers";

const expired = publicationSetup();

describe.each(publicationCases)("$name decoded success publication", ({ request, kind }) => {
  it.each(sessionChanges)("rejects when $name occurs after decoding starts", async (transition) => {
    const body = heldBody(200, kind);
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(request());
    await body.entered;
    expect(body.decode).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await transition.change();
    body.resolve(successfulValue(kind));
    await rejection;
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });

  it("publishes the exact decoded value while the session stays current", async () => {
    const body = heldBody(200, kind);
    const value = successfulValue(kind);
    fetchMock.mockResolvedValueOnce(body.response);
    const requestPromise = request();
    await body.entered;
    body.resolve(value);
    await expect(requestPromise).resolves.toBe(value);
    expectUnchangedCredentials(accessToken("old-access"), expired, 1);
  });
});

describe.each(publicationCases.filter(({ structured }) => structured))(
  "$name decoded error publication", ({ request }) => {
    it.each(sessionChanges)("replaces an old 403 body after $name with session_changed", async (transition) => {
      const body = heldBody(403);
      fetchMock.mockResolvedValueOnce(body.response);
      const rejection = expectSessionChanged(request());
      await body.entered;
      await transition.change();
      body.resolve({ ...oldData, detail: "Account A denied", code: "old_permission" });
      await rejection;
      expect(body.decode).toHaveBeenCalledTimes(1);
      expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
    });

    it("preserves current typed errors and field details without retry", async () => {
      const body = heldBody(403);
      fetchMock.mockResolvedValueOnce(body.response);
      const errorBody = { detail: "Denied", code: "permission_denied", field: ["Invalid"] };
      const rejection = expect(request()).rejects.toMatchObject({ status: 403, code: "permission_denied", body: errorBody });
      await body.entered;
      body.resolve(errorBody);
      await rejection;
      expectUnchangedCredentials(accessToken("old-access"), expired, 1);
    });
  },
);
