import { describe, expect, it, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { usePrefersReducedMotion } from "../../src/hooks/usePrefersReducedMotion";

type Listener = (event: { matches: boolean }) => void;

function installMatchMedia(initialMatches: boolean): { setMatches: (value: boolean) => void; restore: () => void } {
  const original = window.matchMedia;
  const listeners = new Set<Listener>();
  let matches = initialMatches;
  window.matchMedia = ((query: string) => ({
    get matches() {
      return matches;
    },
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return {
    setMatches: (value: boolean) => {
      matches = value;
      for (const listener of listeners) listener({ matches: value });
    },
    restore: () => {
      window.matchMedia = original;
    },
  };
}

describe("usePrefersReducedMotion", () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
  });

  it("reflects the OS preference at mount", () => {
    const media = installMatchMedia(true);
    restore = media.restore;
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
  });

  it("reacts live when the OS preference changes", () => {
    const media = installMatchMedia(false);
    restore = media.restore;
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
    act(() => media.setMatches(true));
    expect(result.current).toBe(true);
  });
});
