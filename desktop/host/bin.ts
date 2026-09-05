/**
 * Process entry point for the Midnight Desktop Host. Resolves the project
 * binding once at startup (the "trusted host, not React" resolution point),
 * then binds loopback-only and listens. Run via `npm run host:start` after
 * `npm run host:build`.
 */

import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { HOST_BIND_ADDRESS, HOST_ENDPOINT_PATH, HOST_PORT } from "./hostConfig.js";
import { ProjectDescriptorError, resolveProjectBinding } from "./projectBinding.js";
import { createHost } from "./server.js";

const HERE = dirname(fileURLToPath(import.meta.url));

function main(): void {
  let binding;
  try {
    binding = resolveProjectBinding(HERE);
  } catch (cause) {
    const message = cause instanceof ProjectDescriptorError ? cause.message : String(cause);
    console.error(`[midnight-desktop-host] invalid project descriptor: ${message}`);
    process.exitCode = 1;
    return;
  }

  const server = createHost(binding);
  server.listen(HOST_PORT, HOST_BIND_ADDRESS, () => {
    console.log(
      `[midnight-desktop-host] listening on http://${HOST_BIND_ADDRESS}:${HOST_PORT}${HOST_ENDPOINT_PATH} (project: ${binding.projectId})`,
    );
  });
}

main();
