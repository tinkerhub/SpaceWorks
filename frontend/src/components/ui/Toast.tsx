import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastTone = "success" | "error" | "warning" | "info";
export type ToastAction = { label: string; onClick: () => void };
export type ToastOptions = { tone?: ToastTone; action?: ToastAction; durationMs?: number };

type ToastState = { id: number; message: string; tone: ToastTone; action?: ToastAction; durationMs: number };

type ToastContextValue = {
  showToast: (message: string, options?: ToastOptions) => void;
  dismissToast: () => void;
};

export const TOAST_DURATION_MS = 4000;

const noop = () => undefined;
// Outside a provider (isolated component tests) toasts are a no-op rather than a crash.
const ToastContext = createContext<ToastContextValue>({ showToast: noop, dismissToast: noop });

const icons: Record<ToastTone, ReactNode> = {
  success: <CheckCircle2 className="text-success" />,
  error: <XCircle className="text-danger" />,
  warning: <AlertTriangle className="text-warn" />,
  info: <Info className="text-accent" />,
};

/**
 * Ink toast: bottom-centre on phones, bottom-left from 640px, 4 seconds, one optional
 * action such as Undo. A newer toast replaces the current one. Errors are announced
 * assertively (role="alert"); everything else politely (role="status"), through two
 * live regions that are always mounted.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const counter = useRef(0);

  const dismissToast = useCallback(() => setToast(null), []);
  const showToast = useCallback((message: string, { tone = "info", action, durationMs = TOAST_DURATION_MS }: ToastOptions = {}) => {
    counter.current += 1;
    setToast({ id: counter.current, message, tone, action, durationMs });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast((current) => (current?.id === toast.id ? null : current)), toast.durationMs);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const value = useMemo(() => ({ showToast, dismissToast }), [showToast, dismissToast]);
  const card = toast ? (
    <div
      key={toast.id}
      className="sw-toast-in pointer-events-auto flex w-full max-w-[460px] items-center gap-3 rounded-lg bg-inverse py-3 pl-4 pr-2 text-body-ui text-on-inverse shadow-float"
    >
      <span aria-hidden="true" className="inline-flex shrink-0 [&_svg]:size-5">{icons[toast.tone]}</span>
      <p className="min-w-0 flex-1">{toast.message}</p>
      {toast.action ? (
        <button
          type="button"
          onClick={() => {
            toast.action?.onClick();
            dismissToast();
          }}
          className="shrink-0 rounded-full px-3 py-1.5 text-sm font-bold underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {toast.action.label}
        </button>
      ) : null}
      <button
        type="button"
        onClick={dismissToast}
        aria-label="Dismiss"
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-full opacity-70 pointer-coarse:size-11 hover:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <X aria-hidden="true" className="size-4" />
      </button>
    </div>
  ) : null;
  const assertive = toast?.tone === "error";

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Both live regions stay mounted from the first render and only their content changes:
          a region that appears (or swaps its role) at the moment it gets text is often missed
          by screen readers. Errors go to the assertive region, everything else to the polite one. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[140] flex flex-col items-center p-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:items-start sm:p-6">
        <div role="status" aria-live="polite" className="flex w-full max-w-[460px] justify-center sm:justify-start">
          {assertive ? null : card}
        </div>
        <div role="alert" aria-live="assertive" className="flex w-full max-w-[460px] justify-center sm:justify-start">
          {assertive ? card : null}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

/** `const { showToast } = useToast(); showToast("Saved", { tone: "success", action: { label: "Undo", onClick } })`. */
export function useToast() {
  return useContext(ToastContext);
}
