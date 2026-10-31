import { accessToken } from "../test/accessTokens";
import { describe, expect, it } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, heldBody,
  publicationSetup, sessionChanges,
} from "./apiResponsePublicationTestHelpers";
import { bootstrapTenant, tenantPublicRequest, tenantPublicRequestBlob } from "./apiRequests";
import { cacheTenantPublishableKey, publicHeaders, tenantPublishableKeys } from "./apiSession";
import { fetchMock, jsonResponse, requestHeaders } from "./apiSessionTestHelpers";

const expired = publicationSetup();
const slug = "publication-cold-tenant";
const bootstrap = {
  makerspace: { slug, name: "Old account tenant" },
  public_api: { publishable_key: "pk_obsolete" },
};
const coldCases = [
  { name: "direct bootstrap", request: () => bootstrapTenant({ slug }) },
  { name: "cold tenant JSON", request: () => tenantPublicRequest(slug, `/public/${slug}/tools`) },
  { name: "cold tenant blob", request: () => tenantPublicRequestBlob(slug, `/public/${slug}/calendar`) },
];

describe.each(coldCases)("$name bootstrap cache publication", ({ request }) => {
  it.each(sessionChanges)("cannot cache an obsolete key after $name during decoding", async (transition) => {
    const body = heldBody(200);
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(request());
    await body.entered;
    expect(tenantPublishableKeys.has(slug)).toBe(false);
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/bootstrap?slug=${slug}`);
    await transition.change();
    body.resolve(bootstrap);
    await rejection;
    expect(tenantPublishableKeys.has(slug)).toBe(false);
    expect(tenantPublishableKeys.get("forge")).toBe("pk_forge");
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });

  it.each(sessionChanges)("cannot overwrite a newer cached key after $name", async (transition) => {
    const body = heldBody(200);
    fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(request());
    await body.entered;
    await transition.change();
    cacheTenantPublishableKey(slug, "pk_current_B");
    body.resolve(bootstrap);
    await rejection;
    expect(tenantPublishableKeys.get(slug)).toBe("pk_current_B");
    expect(new Headers(await publicHeaders()).get("X-Publishable-Key")).toBe("pk_current_B");
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });
});

it("caches a current decoded bootstrap and uses that key on the next tenant request", async () => {
  const body = heldBody(200);
  fetchMock.mockResolvedValueOnce(body.response);
  const pending = bootstrapTenant({ slug });
  await body.entered;
  expect(tenantPublishableKeys.has(slug)).toBe(false);
  body.resolve(bootstrap);
  await expect(pending).resolves.toBe(bootstrap);
  expect(tenantPublishableKeys.get(slug)).toBe("pk_obsolete");

  fetchMock.mockResolvedValueOnce(jsonResponse(200, { results: [] }));
  await expect(tenantPublicRequest(slug, `/public/${slug}/tools`)).resolves.toEqual({ results: [] });
  expect(requestHeaders(1).get("X-Publishable-Key")).toBe("pk_obsolete");
  expectUnchangedCredentials(accessToken("old-access"), expired, 2);
});
