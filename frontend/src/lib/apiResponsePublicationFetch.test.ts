import { accessToken } from "../test/accessTokens";
import { describe, expect, it, vi } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, oldData, publicationCases,
  publicationSetup, sessionChanges,
} from "./apiResponsePublicationTestHelpers";
import { setAccessToken } from "./apiSession";
import { fetchMock, heldResponse, jsonResponse } from "./apiSessionTestHelpers";

const expired = publicationSetup();

describe.each(publicationCases)("$name successful fetch publication", ({ request }) => {
  it.each(sessionChanges)("rejects a held 200 after $name before decoding", async (transition) => {
    const held = heldResponse();
    const response = jsonResponse(200, oldData);
    const json = vi.spyOn(response, "json");
    const blob = vi.spyOn(response, "blob");
    fetchMock.mockImplementationOnce(held.send);
    const rejection = expectSessionChanged(request());
    await held.entered;
    await transition.change();
    held.resolve(response);
    await rejection;

    expect(json).not.toHaveBeenCalled();
    expect(blob).not.toHaveBeenCalled();
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });
});

const noContentCases = publicationCases.filter(({ name }) => name === "staff JSON" || name === "member JSON");
describe.each(noContentCases)("$name bodyless publication", ({ request }) => {
  it.each(sessionChanges)("rejects a held 204 after $name", async (transition) => {
    const held = heldResponse();
    fetchMock.mockImplementationOnce(held.send);
    const rejection = expectSessionChanged(request());
    await held.entered;
    await transition.change();
    held.resolve(jsonResponse(204));
    await rejection;
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });

  it("returns undefined for a current 204 without trying to decode it", async () => {
    const response = jsonResponse(204);
    const json = vi.spyOn(response, "json");
    const blob = vi.spyOn(response, "blob");
    fetchMock.mockResolvedValueOnce(response);
    await expect(request()).resolves.toBeUndefined();
    expect(json).not.toHaveBeenCalled();
    expect(blob).not.toHaveBeenCalled();
    expectUnchangedCredentials(accessToken("old-access"), expired, 1);
  });

  it("checks ownership again when a 204 settles across a new login microtask", async () => {
    const response = jsonResponse(204);
    // ok is inspected by the decoder, after staffFetch's status/epoch checks.
    // The queued login runs after its bodyless return, before wrapper publication.
    vi.spyOn(response, "ok", "get").mockImplementation(() => {
      queueMicrotask(() => setAccessToken(accessToken("account-B", { user_id: 2 })));
      return true;
    });
    fetchMock.mockResolvedValueOnce(response);
    await expectSessionChanged(request());
    expectUnchangedCredentials(accessToken("account-B", { user_id: 2 }), expired, 1);
  });
});
