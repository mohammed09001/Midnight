import { afterEach, describe, expect, it } from "vitest";
import type { Server } from "node:http";
import { createHost } from "../../host/server";
import { HOST_BIND_ADDRESS, HOST_ENDPOINT_PATH } from "../../host/hostConfig";
import type { ProjectBinding } from "../../host/projectBinding";
import type { Operation } from "../../host/operations/activityListPromptRuns";
import { activityListPromptRuns } from "../../host/operations/activityListPromptRuns";

const fakeBinding: ProjectBinding = {
  descriptorVersion: 1,
  projectId: "test-project",
  performanceDataDir: "/nonexistent/Performance/data",
  projectRoot: "/nonexistent",
  workspaceId: null,
};

let server: Server | null = null;

afterEach(async () => {
  if (server) {
    await new Promise<void>((resolvePromise) => server!.close(() => resolvePromise()));
    server = null;
  }
});

async function start(
  operations: Readonly<Record<string, Operation>>,
  requestTimeoutMs?: number,
): Promise<string> {
  server = createHost(fakeBinding, { operations, requestTimeoutMs });
  await new Promise<void>((resolvePromise) => server!.listen(0, HOST_BIND_ADDRESS, () => resolvePromise()));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("expected a TCP address");
  return `http://${HOST_BIND_ADDRESS}:${address.port}`;
}

function envelope(body: Record<string, unknown>): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

const stubOk: Operation = async () => ({ ok: "stub" });

describe("Desktop Host server (Execution 03 security surface)", () => {
  it("binds loopback only", () => {
    expect(HOST_BIND_ADDRESS).toBe("127.0.0.1");
  });

  it("serves a real request over the loopback address", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 1, operation: "test.echo", request: {} }));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ contractVersion: 1, operation: "test.echo", ok: true, result: { ok: "stub" } });
  });

  it("rejects non-POST methods with a typed 405", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, { method: "GET" });
    expect(response.status).toBe(405);
    const body = await response.json();
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("METHOD_NOT_ALLOWED");
  });

  it("rejects an oversized request body before parsing it", async () => {
    const base = await start({ "test.echo": stubOk });
    const hugeCursor = "x".repeat(64 * 1024);
    const response = await fetch(
      `${base}${HOST_ENDPOINT_PATH}`,
      envelope({ contractVersion: 1, operation: "test.echo", request: { cursor: hugeCursor } }),
    );
    expect(response.status).toBe(413);
    const body = await response.json();
    expect(body.error.code).toBe("PAYLOAD_TOO_LARGE");
  });

  it("never emits CORS headers", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 1, operation: "test.echo", request: {} }));
    expect(response.headers.get("access-control-allow-origin")).toBeNull();
    expect(response.headers.get("access-control-allow-methods")).toBeNull();
  });

  it("rejects a contractVersion mismatch with a typed 409", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 99, operation: "test.echo", request: {} }));
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.error.code).toBe("UNSUPPORTED_CONTRACT_VERSION");
  });

  it("rejects an unknown operation with a typed 400", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 1, operation: "no.such.op", request: {} }));
    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.error.code).toBe("UNKNOWN_OPERATION");
  });

  it("rejects a malformed envelope (fails schema validation) with a typed 400", async () => {
    const base = await start({ "test.echo": stubOk });
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 1, operation: "test.echo" }));
    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.error.code).toBe("INVALID_REQUEST");
  });

  it("rejects a renderer request carrying an arbitrary filesystem path field", async () => {
    const base = await start({ "activity.listPromptRuns": activityListPromptRuns });
    const response = await fetch(
      `${base}${HOST_ENDPOINT_PATH}`,
      envelope({
        contractVersion: 1,
        operation: "activity.listPromptRuns",
        request: { path: "C:/Windows/System32", dataDir: "/etc" },
      }),
    );
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("INVALID_REQUEST");
  });

  it("handles a hung operation as a graceful, typed timeout rather than hanging the response", async () => {
    const neverResolves: Operation = () => new Promise(() => {});
    const base = await start({ "test.hang": neverResolves }, 200);
    const response = await fetch(`${base}${HOST_ENDPOINT_PATH}`, envelope({ contractVersion: 1, operation: "test.hang", request: {} }));
    expect(response.status).toBe(504);
    const body = await response.json();
    expect(body.error.code).toBe("BRIDGE_TIMEOUT");
  }, 5_000);
});
