import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function currentPreference(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(QUERY).matches;
}

/**
 * Gates elkjs/React Flow's animated transitions (fit-view, layout changes).
 * Reacts live to a changed OS setting, not just its value at mount.
 */
export function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(currentPreference);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mediaQueryList = window.matchMedia(QUERY);
    const listener = () => setPrefersReduced(mediaQueryList.matches);
    listener();
    mediaQueryList.addEventListener("change", listener);
    return () => mediaQueryList.removeEventListener("change", listener);
  }, []);

  return prefersReduced;
}
