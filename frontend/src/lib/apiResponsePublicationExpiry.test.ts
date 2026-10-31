import { accessToken } from "../test/accessTokens";
import { describe, expect, it, vi } from "vitest";

import {
  expectSessionChanged, heldBody, publicationCases, publicationSetup, sessionChanges,
} from "./apiResponsePublicationTestHelpers";
import { addAuthExpiredListener, getAccessToken, getSessionGeneration } from "./apiSession";
import { fetchMock, jsonResponse } from "./apiSessionTestHelpers";

const expired = publicationSetup();
const authenticatedCases = publicationCases.filter(({ retry, tenant }) => retry && !tenant);

describe.each(authenticatedCases)("$name own expiry publication", ({ request }) => {
  describe.each(["failed refresh", "retried 401"] as const)("%s", (failure) => {
    function queueExpiry(response: Response) {
      if (failure === "failed refresh") {
        fetchMock.mockResolvedValueOnce(response).mockResolvedValueOnce(jsonResponse(401));
      } else {
        fetchMock.mockResolvedValueOnce(jsonResponse(401))
          .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("rotated-A") }))
          .mockResolvedValueOnce(response);
      }
    }
    const calls = failure === "failed refresh" ? 2 : 3;

    it("preserves its genuine typed 401 and emits expiry exactly once", async () => {
      const generation = getSessionGeneration();
      const body = heldBody(401);
      queueExpiry(body.response);
      const rejection = expect(request()).rejects.toMatchObject({
        status: 401, code: "token_not_valid", body: { code: "token_not_valid", detail: "Session expired" },
      });
      await body.entered;
      expect(getSessionGeneration()).toBe(generation + 1);
      expect(getAccessToken()).toBe("");
      expect(expired).toHaveBeenCalledTimes(1);
      body.resolve({ code: "token_not_valid", detail: "Session expired" });
      await rejection;
      expect(expired).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(calls);
    });

    it.each(sessionChanges)("does not adopt a listener's synchronous $name", async (transition) => {
      const response = jsonResponse(401, { detail: "Obsolete expiry" });
      const decode = vi.spyOn(response, "json");
      queueExpiry(response);
      let changed: Promise<void> | undefined;
      const unsubscribe = addAuthExpiredListener(() => { changed = transition.change(); });
      try {
        await expectSessionChanged(request());
        expect(changed).toBeDefined();
        await changed;
        expect(getAccessToken()).toBe(transition.token);
        // This is the request's genuine expiry event, before the listener changed
        // the session. It must never be emitted again for the now-obsolete work.
        expect(expired).toHaveBeenCalledTimes(1);
        expect(decode).not.toHaveBeenCalled();
        expect(fetchMock).toHaveBeenCalledTimes(calls + (transition.logout ? 1 : 0));
      } finally {
        unsubscribe();
      }
    });

    it.each(sessionChanges)("rejects an expiry body decoded across a subsequent $name", async (transition) => {
      const body = heldBody(401);
      queueExpiry(body.response);
      const rejection = expectSessionChanged(request());
      await body.entered;
      expect(expired).toHaveBeenCalledTimes(1);
      await transition.change();
      body.resolve({ detail: "Old expiry data", code: "old_expiry" });
      await rejection;
      expect(getAccessToken()).toBe(transition.token);
      expect(expired).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(calls + (transition.logout ? 1 : 0));
    });
  });
});
