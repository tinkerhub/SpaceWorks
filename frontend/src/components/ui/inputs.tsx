import { forwardRef, useState, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Eye, EyeOff, Search, X } from "lucide-react";

import { cn } from "../../lib/cn";
import { controlClasses, markFieldControl, readOnlyClasses } from "./Field";

const innerButton =
  "absolute right-1 top-1/2 inline-flex size-9 -translate-y-1/2 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-emphasis hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-focus";

export const Input = markFieldControl(
  forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(controlClasses, readOnlyClasses, className)} {...props} />;
  }),
);

export const Textarea = markFieldControl(
  forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, rows = 4, ...props }, ref) {
    return <textarea ref={ref} rows={rows} className={cn(controlClasses, readOnlyClasses, "min-h-24 resize-y", className)} {...props} />;
  }),
);

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  /** Accessible names for the toggle. */
  showLabel?: string;
  hideLabel?: string;
};

/** Password field with an inline show/hide button inside the same border. */
export const PasswordInput = markFieldControl(
  forwardRef<HTMLInputElement, PasswordInputProps>(function PasswordInput(
    { className, showLabel = "Show password", hideLabel = "Hide password", ...props },
    ref,
  ) {
    const [visible, setVisible] = useState(false);
    return (
      <div className="relative min-w-0">
        <input ref={ref} type={visible ? "text" : "password"} className={cn(controlClasses, "pr-12", className)} {...props} />
        <button
          type="button"
          onClick={() => setVisible((value) => !value)}
          aria-label={visible ? hideLabel : showLabel}
          aria-pressed={visible}
          disabled={props.disabled}
          className={innerButton}
        >
          {visible ? <EyeOff aria-hidden="true" className="size-[18px]" /> : <Eye aria-hidden="true" className="size-[18px]" />}
        </button>
      </div>
    );
  }),
);

type SearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  /** Shows the clear button while there is a value. */
  onClear?: () => void;
  clearLabel?: string;
};

/** Pill search field with a leading icon and a clear button. */
export const SearchInput = markFieldControl(
  forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
    { className, onClear, clearLabel = "Clear search", value, ...props },
    ref,
  ) {
    const hasValue = typeof value === "string" ? value.length > 0 : value !== undefined && value !== null;
    return (
      <div className="relative min-w-0">
        <Search aria-hidden="true" className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-ink-muted" />
        <input
          ref={ref}
          type="search"
          value={value}
          className={cn(controlClasses, "rounded-full pl-11 pr-11 [&::-webkit-search-cancel-button]:appearance-none", className)}
          {...props}
        />
        {onClear && hasValue ? (
          <button type="button" onClick={onClear} aria-label={clearLabel} className={innerButton}>
            <X aria-hidden="true" className="size-4" />
          </button>
        ) : null}
      </div>
    );
  }),
);
