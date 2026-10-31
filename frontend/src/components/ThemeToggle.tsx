import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

import { writeStorage } from "../lib/safeStorage";
import { Button } from "./ui/Button";
import { IconButton, type IconButtonSize } from "./ui/IconButton";

const THEME_KEY = "makerspace.theme";

export type Theme = "light" | "dark";

// The `.dark` class on <html> is the single source of truth (main.tsx applies the stored
// choice before the first render). Every toggle on screen subscribes to it, so a menu item
// and an icon button can never disagree about the current mode.
const listeners = new Set<() => void>();

function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  writeStorage(THEME_KEY, theme);
  listeners.forEach((listener) => listener());
}

/** The current light/dark mode and a toggle. The choice is stored per browser. */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, currentTheme, (): Theme => "light");
  return { theme, toggle: () => setTheme(theme === "dark" ? "light" : "dark") };
}

/** Sun/moon pair that cross-rotates, so the swap reads as one motion. */
export function ThemeIcon({ theme }: { theme: Theme }) {
  return (
    <span aria-hidden="true" className="relative inline-flex size-[18px] shrink-0">
      <Sun className={`absolute inset-0 size-[18px] transition duration-300 ease-standard motion-reduce:transition-none ${theme === "dark" ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-50 opacity-0"}`} />
      <Moon className={`absolute inset-0 size-[18px] transition duration-300 ease-standard motion-reduce:transition-none ${theme === "dark" ? "rotate-90 scale-50 opacity-0" : "rotate-0 scale-100 opacity-100"}`} />
    </span>
  );
}

type ThemeToggleProps = {
  variant?: "text" | "icon";
  /** Icon variant only. */
  size?: IconButtonSize;
};

/** Light/dark switch. The choice is stored per browser and applied as `.dark` on <html>. */
export function ThemeToggle({ variant = "text", size = "md" }: ThemeToggleProps) {
  const { theme, toggle } = useTheme();
  const icons = <ThemeIcon theme={theme} />;

  if (variant === "icon") {
    return (
      <IconButton label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} variant="quiet" size={size} onClick={toggle}>
        {icons}
      </IconButton>
    );
  }

  return (
    <Button variant="secondary" size="sm" startIcon={icons} onClick={toggle}>
      {theme === "dark" ? "Light" : "Dark"}
    </Button>
  );
}
