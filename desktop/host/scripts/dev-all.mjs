#!/usr/bin/env node
/**
 * One-command local dev convenience: builds and starts the Midnight Desktop
 * Host, then starts Vite dev (which proxies to it). Plain `child_process`
 * only — no `concurrently`/`nodemon` dependency added.
 */
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const desktopDir = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const isWindows = process.platform === "win32";
const npmCmd = isWindows ? "npm.cmd" : "npm";

function run(command, args) {
  return spawn(command, args, { cwd: desktopDir, stdio: "inherit", shell: isWindows });
}

console.log("[dev-all] building the Desktop Host...");
const build = spawnSync(npmCmd, ["run", "host:build"], { cwd: desktopDir, stdio: "inherit", shell: isWindows });
if (build.status !== 0) {
  console.error("[dev-all] Desktop Host build failed; aborting.");
  process.exit(build.status ?? 1);
}

const children = [run(npmCmd, ["run", "host:start"]), run(npmCmd, ["run", "dev"])];

function shutdown() {
  for (const child of children) child.kill();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
for (const child of children) {
  child.on("exit", (code) => {
    console.log(`[dev-all] a child process exited (code ${code}); shutting down the rest.`);
    shutdown();
  });
}
