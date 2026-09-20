/**
 * Theme: light, dark, or follow the system.
 *
 * tokens.css defines the light palette on :root, overrides it under
 * [data-theme="dark"], and also honours prefers-color-scheme when no data-theme is
 * set. So "system" means removing the attribute, not computing a value.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "helmly.theme";

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // private browsing or blocked storage: fall through to the default
  }
  return "system";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/** Called once before React mounts, so the first paint is already correct. */
export function initTheme(): void {
  applyTheme(readTheme());
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // the theme still applies for this session
    }
  }, []);

  return [theme, setTheme];
}
