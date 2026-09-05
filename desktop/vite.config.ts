/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { HOST_BIND_ADDRESS, HOST_ENDPOINT_PATH, HOST_PORT, PROXY_PATH } from "./host/hostConfig";

// Execution 03: Vite is a pure dev/preview proxy, never the product
// authority. The Midnight Desktop Host (`desktop/host/`) is a standalone
// process that owns project-identity resolution, the Performance bridge
// subprocess, and contract validation — Vite no longer spawns Python or
// resolves any path itself.
const hostTarget = `http://${HOST_BIND_ADDRESS}:${HOST_PORT}`;

const proxyConfig = {
  [PROXY_PATH]: {
    target: hostTarget,
    changeOrigin: false,
    rewrite: () => HOST_ENDPOINT_PATH,
  },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy: proxyConfig },
  preview: { proxy: proxyConfig },
  test: {
    // Execution 07: component tests (React Flow / RTL, needing a DOM) are
    // split into their own project so the existing node-environment unit
    // suite keeps its current speed and behavior unchanged — the two never
    // share an environment, matching neither set of tests' actual needs.
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          include: ["tests/**/*.test.ts"],
          exclude: ["tests/components/**", "tests/hooks/**"],
        },
      },
      {
        extends: true,
        test: {
          name: "component",
          environment: "jsdom",
          include: ["tests/components/**/*.test.{ts,tsx}", "tests/hooks/**/*.test.{ts,tsx}"],
          setupFiles: ["./tests/setupTests.ts"],
        },
      },
    ],
  },
});
