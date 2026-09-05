import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
});

// jsdom implements neither ResizeObserver nor DOMMatrixReadOnly — both are
// required internally by @xyflow/react's viewport/container sizing. Real
// layout measurement isn't meaningful under jsdom regardless (no real
// paint), so a no-op stub is sufficient to let PerformanceGraph mount and
// exercise everything except literal pixel geometry.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// jsdom does not implement matchMedia — `usePrefersReducedMotion` and any
// other `prefers-*` media-query consumer needs a stand-in. Individual tests
// override `window.matchMedia` per-case to simulate a specific query result;
// this default just keeps every OTHER test (that never touches the hook)
// from crashing on an undefined call.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}
