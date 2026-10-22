import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/figtree";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";

import App from "./App";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { ToastProvider } from "./components/ui/Toast";
import "./index.css";
import { cleanupLegacyAccessToken } from "./lib/api";
import { queryClient } from "./lib/queryClient";
import { TenantProvider } from "./lib/tenant";
import { readStorage } from "./lib/safeStorage";
import { pruneExpiredOfflineStates } from "./features/staff/eventCheckInOfflineStore";

if (readStorage("makerspace.theme") === "dark") {
  document.documentElement.classList.add("dark");
}
cleanupLegacyAccessToken();
void pruneExpiredOfflineStates().catch(() => undefined);
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <TenantProvider>
        <BrowserRouter>
          <ToastProvider>
            <AppErrorBoundary>
              <App />
            </AppErrorBoundary>
          </ToastProvider>
        </BrowserRouter>
      </TenantProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
