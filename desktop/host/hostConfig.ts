/**
 * Single source of truth for the Midnight Desktop Host's network surface.
 * Imported both by `desktop/vite.config.ts` (dev/preview proxy target) and
 * by `desktop/host/server.ts` (what actually binds the port) so the two
 * never drift.
 */

export const CONTRACT_VERSION = 1;

export const DEFAULT_HOST_PORT = 52173;

export const HOST_PORT = (() => {
  const raw = process.env.MIDNIGHT_DESKTOP_HOST_PORT;
  if (!raw) return DEFAULT_HOST_PORT;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 && parsed < 65536 ? parsed : DEFAULT_HOST_PORT;
})();

/** The Host's own listening surface — never anything but loopback. */
export const HOST_BIND_ADDRESS = "127.0.0.1";

/** The single dispatch endpoint on the Host. */
export const HOST_ENDPOINT_PATH = "/contract";

/** The path the Vite dev/preview server proxies to the Host. */
export const PROXY_PATH = "/api/desktop-host";

/** Bodies are tiny ({limit, cursor} at most) — reject anything larger before parsing. */
export const MAX_REQUEST_BODY_BYTES = 16 * 1024;

/** Wall-clock cap on the whole request, independent of the bridge's own timeout. */
export const REQUEST_TIMEOUT_MS = 12_000;

/** Cap on the spawned Python bridge subprocess. */
export const BRIDGE_TIMEOUT_MS = 10_000;
