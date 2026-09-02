/// <reference types="vitest" />
import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Connect, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Midnight Desktop is a Vite-served local client. The repository's only
// existing cross-process convention (Performance -> Memory) is a versioned
// JSON document exchanged with a subprocess CLI, so the Desktop uses the
// same pattern: its dev/preview server spawns the read-only Performance
// bridge (`python -m midnight_performance.desktop_bridge`) and relays the
// bounded JSON to the browser at a single local route. No second server, no
// ledger access from browser code, and the bridge itself has no write path.
const performancePackageDir = fileURLToPath(new URL("../Performance", import.meta.url));
const performanceDataDir = path.join(performancePackageDir, "data");
const pythonExecutable = process.env.MIDNIGHT_PYTHON || "python";
const BRIDGE_TIMEOUT_MS = 10_000;

function bridgeHandler(res: Connect.ServerResponse): void {
  res.setHeader("Cache-Control", "no-store");
  execFile(
    pythonExecutable,
    [
      "-m",
      "midnight_performance.desktop_bridge",
      "--data-dir",
      performanceDataDir,
      "--project",
      "midnight",
    ],
    {
      cwd: performancePackageDir,
      timeout: BRIDGE_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 8 * 1024 * 1024,
    },
    (error, stdout) => {
      res.setHeader("Content-Type", "application/json");
      if (error) {
        // Python missing, ledger unreadable, or timeout: an honest 503, which
        // the Desktop renders as a calm "Performance source unavailable".
        res.statusCode = 503;
        res.end(JSON.stringify({ version: 1, status: "unavailable", reason: String(error.message) }));
        return;
      }
      res.end(stdout);
    },
  );
}

function performanceActivityBridge(): Plugin {
  const middleware: Connect.NextHandleFunction = (_req, res) => bridgeHandler(res);
  return {
    name: "midnight-performance-activity-bridge",
    configureServer(server) {
      server.middlewares.use("/api/activity/prompt-runs", middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/api/activity/prompt-runs", middleware);
    },
  };
}

export default defineConfig({
  plugins: [react(), performanceActivityBridge()],
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
