import { accessToken } from "../../../../test/accessTokens";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach } from "vitest";

import { clearAccessToken, getSessionGeneration, setAccessToken } from "../../../../lib/api";
import { staffMakerspacesKey } from "../../useStaffMakerspaces";
import type { Makerspace } from "../shared";

/** Use real auth epochs so no fixture can inherit a previous test's session. */
export function isolateMachineTestSession() {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setAccessToken(accessToken("machine-console-test-session", { surface: "staff", staff_scope: "platform" }));
  });
  afterEach(() => {
    clearAccessToken();
    localStorage.clear();
    sessionStorage.clear();
  });
}

export function machineTestMakerspaces(makerspaceId = 1): Makerspace[] {
  return [{
    id: makerspaceId, name: "Test lab", slug: `lab-${makerspaceId}`,
    public_code: `lab-${makerspaceId}`, telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false,
    enabled_modules: ["machines", "machine_service", "printing", "payments"],
  }];
}

export function machineConsoleTestClient(makerspaceId = 1) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // These leaf consoles normally mount after the chooser warms this session's list.
  // Leave normal refetch behavior intact; API fixtures also return the allowed list.
  client.setQueryData(staffMakerspacesKey(getSessionGeneration()), machineTestMakerspaces(makerspaceId));
  return client;
}
