import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  expectSessionChanged, expectUnchangedCredentials, heldBody,
  oldData, publicationSetup, sessionChanges, successfulValue,
} from "./apiResponsePublicationTestHelpers";
import { downloadStaffFile } from "./apiRequests";
import { fetchMock, heldResponse } from "./apiSessionTestHelpers";

const expired = publicationSetup();
const createObjectURL = vi.fn<(blob: Blob) => string>();
const revokeObjectURL = vi.fn<(url: string) => void>();
const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
const clicked = vi.fn();

beforeEach(() => {
  createObjectURL.mockReset().mockReturnValue("blob:http://localhost/current-report");
  revokeObjectURL.mockReset();
  clicked.mockReset();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
});
afterEach(() => {
  if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
});

describe.each(["fetch", "blob body"] as const)("download publication held at %s", (boundary) => {
  it.each(sessionChanges)("does not create a file URL or click after $name", async (transition) => {
    const held = heldResponse();
    const body = heldBody(200, "blob");
    if (boundary === "fetch") fetchMock.mockImplementationOnce(held.send);
    else fetchMock.mockResolvedValueOnce(body.response);
    const rejection = expectSessionChanged(downloadStaffFile("/admin/reports/export", "private.csv"));
    await (boundary === "fetch" ? held.entered : body.entered);
    await transition.change();
    if (boundary === "fetch") held.resolve(new Response(JSON.stringify(oldData)));
    else body.resolve(successfulValue("blob"));
    await rejection;
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clicked).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    expectUnchangedCredentials(transition.token, expired, transition.logout ? 2 : 1);
  });
});

it("downloads and revokes the exact currently decoded blob once", async () => {
  const body = heldBody(200, "blob");
  const value = successfulValue("blob");
  fetchMock.mockResolvedValueOnce(body.response);
  const pending = downloadStaffFile("/admin/reports/export", "current.csv");
  await body.entered;
  body.resolve(value);
  await pending;
  expect(createObjectURL).toHaveBeenCalledExactlyOnceWith(value);
  expect(clicked).toHaveBeenCalledTimes(1);
  const link = clicked.mock.contexts[0] as HTMLAnchorElement;
  expect(link.download).toBe("current.csv");
  expect(link.href).toBe("blob:http://localhost/current-report");
  expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:http://localhost/current-report");
  expectUnchangedCredentials(accessToken("old-access"), expired, 1);
});
