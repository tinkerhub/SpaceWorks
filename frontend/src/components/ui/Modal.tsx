import type React from "react";
import { useEffect, useId, useRef, useSyncExternalStore } from "react";
import { X } from "lucide-react";

import { cn } from "../../lib/cn";
import {
  consumePendingRestore,
  focusFirstDialogElement,
  getSnapshot,
  popDialog,
  pushDialog,
  subscribe,
  trapDialogFocus,
} from "./dialogFocus";
import { IconButton } from "./IconButton";

export type DialogSize = "sm" | "md" | "lg" | "xl";

export type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  /** One line under the title; becomes the dialog's accessible description. */
  description?: React.ReactNode;
  children: React.ReactNode;
  /** Actions, right-aligned: secondary first, then the primary/danger action. */
  footer?: React.ReactNode;
  size?: DialogSize;
  backdrop?: "plain" | "blur";
  /** `alertdialog` for confirmations that interrupt. */
  role?: "dialog" | "alertdialog";
  /** Hide the corner close button (Escape and the backdrop still close). */
  hideClose?: boolean;
  closeLabel?: string;
};

const sizeClasses: Record<DialogSize, string> = {
  sm: "max-w-[480px]",
  md: "max-w-[560px]",
  lg: "max-w-[760px]",
  xl: "max-w-[960px]",
};

/**
 * The one dialog. Rounded-2xl canvas panel over a dimmed scrim, title + body + actions.
 * Focus, Escape and stacking go through `dialogFocus`: only the topmost dialog reacts,
 * covered dialogs become `inert`, and closing restores focus to the opener.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  backdrop = "plain",
  role = "dialog",
  hideClose = false,
  closeLabel = "Close dialog",
}: ModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const layerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const tokenRef = useRef<symbol | null>(null);
  const top = useSyncExternalStore(subscribe, getSnapshot);
  const amTop = tokenRef.current !== null && top === tokenRef.current;
  const amTopRef = useRef(amTop);
  amTopRef.current = amTop;
  // Keep onClose in a ref so the focus effect depends only on `open`. Callers pass a
  // fresh inline onClose every render; if it were in the dep array, every keystroke
  // (which re-renders the parent) would re-run this effect and steal focus back to the
  // first field. The ref lets Escape always call the latest onClose without that churn.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const token = pushDialog({
      previousFocus,
      getPanel: () => panelRef.current,
      getLayer: () => layerRef.current,
    });
    tokenRef.current = token;
    const panel = panelRef.current;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!amTopRef.current) return;
      // A listbox or menu open inside the dialog handles (and prevents) its own Escape.
      if (event.key === "Escape" && !event.defaultPrevented) onCloseRef.current();
      if (panel) trapDialogFocus(event, panel);
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      popDialog(token);
      if (tokenRef.current === token) tokenRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!amTop) return;
    consumePendingRestore(panelRef.current);
    // Initial focus lives HERE, not in the push effect. A dialog that opens while another sits
    // above it renders with `inert` on its layer, and `inert` is only cleared by the re-render
    // that follows becoming topmost -- so focusing from the push effect silently fails, and
    // consumePendingRestore no-ops because nothing was popped. This effect runs post-commit,
    // once `inert` is gone. jsdom implements no `inert` at all, so no unit test can catch this.
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) focusFirstDialogElement(panel);
  }, [amTop]);

  if (!open) return null;

  return (
    <div
      ref={layerRef}
      inert={!amTop}
      className={cn("dialog-overlay sw-overlay-in fixed inset-0 z-50 grid place-items-center bg-overlay", backdrop === "blur" && "backdrop-blur-sm")}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role={role}
        aria-modal={amTop ? "true" : undefined}
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "dialog-panel desk-panel sw-dialog-in relative flex w-full flex-col overflow-y-auto rounded-2xl border-line bg-canvas text-ink shadow-float focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
          sizeClasses[size],
        )}
      >
        {/* The close button comes last in the DOM so initial focus lands on the content. */}
        <div className={cn("flex shrink-0 flex-col gap-1.5 px-5 pb-2 pt-5 sm:px-6 sm:pt-6", !hideClose && "pr-14 sm:pr-14")}>
          <h2 id={titleId} className="text-h3 text-ink">
            {title}
          </h2>
          {description ? <p id={descriptionId} className="text-body-ui text-ink-secondary">{description}</p> : null}
        </div>
        <div className="desk-panel-body min-h-[min(6rem,25dvh)] min-w-0 overflow-y-auto overflow-x-hidden px-5 py-3 sm:px-6">{children}</div>
        {footer ? <div className="shrink-0 px-5 pb-5 pt-3 sm:px-6 sm:pb-6">{footer}</div> : null}
        {hideClose ? null : (
          <IconButton label={closeLabel} variant="quiet" size="sm" className="absolute right-3 top-3" onClick={onClose}>
            <X aria-hidden="true" />
          </IconButton>
        )}
      </div>
    </div>
  );
}

/** Same component under the reference name; prefer `Dialog` in new code. */
export const Dialog = Modal;
export type DialogProps = ModalProps;
