/**
 * The Midnight Desktop Host: a small, standalone, read-only local service
 * boundary. Binds loopback only, exposes one dispatch endpoint, validates
 * every request/response against the shared contract schema, and never
 * throws an uncaught error across the HTTP boundary — every response is a
 * typed envelope. Read-only by construction: `OPERATIONS` (imported from
 * `operations/registry.ts`) contains no write-shaped operation.
 *
 * This module is a pure factory (`createHost`) with no side effects on
 * import, so tests can construct a server against a stub project binding on
 * an ephemeral port without ever touching the real Python bridge. The actual
 * process entry point lives in `bin.ts`.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { CONTRACT_VERSION, HOST_ENDPOINT_PATH, MAX_REQUEST_BODY_BYTES, REQUEST_TIMEOUT_MS } from "./hostConfig.js";
import { errorEnvelope, HostError, successEnvelope, type HostResponseEnvelope } from "./envelope.js";
import type { ProjectBinding } from "./projectBinding.js";
import { loadSchema, validate } from "./schemaValidator.js";
import { OPERATIONS } from "./operations/registry.js";
import type { Operation } from "./operations/activityListPromptRuns.js";

function writeEnvelope(res: ServerResponse, status: number, envelope: HostResponseEnvelope): void {
  const body = JSON.stringify(envelope);
  if (!res.headersSent) {
    // No Access-Control-* headers are ever emitted: the browser's
    // same-origin policy is the enforcement mechanism, and nothing here
    // opts a foreign origin in.
    res.writeHead(status, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "Content-Length": Buffer.byteLength(body),
    });
  }
  res.end(body);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    let size = 0;
    let rejected = false;
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => {
      if (rejected) return;
      size += chunk.length;
      if (size > MAX_REQUEST_BODY_BYTES) {
        // Reject without destroying the socket — destroying it here would
        // tear down the response too, since request and response share the
        // same connection. Just stop accumulating; the caller still writes
        // a proper typed 413 on the still-open connection.
        rejected = true;
        reject(new HostError("PAYLOAD_TOO_LARGE", `request body exceeds ${MAX_REQUEST_BODY_BYTES} bytes`));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (!rejected) resolvePromise(Buffer.concat(chunks).toString("utf-8"));
    });
    req.on("error", (cause) => reject(cause instanceof Error ? cause : new Error(String(cause))));
  });
}

function withTimeout(ms: number, message: string) {
  let timer: ReturnType<typeof setTimeout>;
  const promise = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new HostError("BRIDGE_TIMEOUT", message)), ms);
  });
  return { promise, clear: () => clearTimeout(timer!) };
}

export interface CreateHostOptions {
  readonly operations?: Readonly<Record<string, Operation>>;
  readonly requestTimeoutMs?: number;
}

export function createHost(binding: ProjectBinding, options: CreateHostOptions = {}): Server {
  const operations = options.operations ?? OPERATIONS;
  const requestTimeoutMs = options.requestTimeoutMs ?? REQUEST_TIMEOUT_MS;

  const server = createServer((req, res) => {
    void handleRequest(req, res, binding, operations, requestTimeoutMs);
  });
  server.requestTimeout = requestTimeoutMs + 2_000;
  return server;
}

async function handleRequest(
  req: IncomingMessage,
  res: ServerResponse,
  binding: ProjectBinding,
  operations: Readonly<Record<string, Operation>>,
  requestTimeoutMs: number,
): Promise<void> {
  if (req.url !== HOST_ENDPOINT_PATH) {
    writeEnvelope(res, 404, errorEnvelope(null, "UNKNOWN_OPERATION", `no such endpoint: ${req.url ?? ""}`));
    return;
  }
  if (req.method !== "POST") {
    writeEnvelope(res, 405, errorEnvelope(null, "METHOD_NOT_ALLOWED", `method ${req.method ?? "?"} is not allowed`));
    return;
  }

  const timeout = withTimeout(requestTimeoutMs, `request exceeded ${requestTimeoutMs}ms`);
  try {
    const bodyText = await Promise.race([readBody(req), timeout.promise]);

    let parsed: unknown;
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      writeEnvelope(res, 400, errorEnvelope(null, "INVALID_REQUEST", "request body is not valid JSON"));
      return;
    }

    const envelopeViolations = validate(loadSchema("host-envelope.schema.json"), parsed);
    if (envelopeViolations.length > 0) {
      writeEnvelope(res, 400, errorEnvelope(null, "INVALID_REQUEST", envelopeViolations.join("; ")));
      return;
    }
    const envelope = parsed as { contractVersion: number; operation: string; request: Record<string, unknown> };

    if (envelope.contractVersion !== CONTRACT_VERSION) {
      writeEnvelope(
        res,
        409,
        errorEnvelope(
          envelope.operation,
          "UNSUPPORTED_CONTRACT_VERSION",
          `unsupported contractVersion: ${envelope.contractVersion} (expected ${CONTRACT_VERSION})`,
        ),
      );
      return;
    }

    const operation = operations[envelope.operation];
    if (!operation) {
      writeEnvelope(res, 400, errorEnvelope(envelope.operation, "UNKNOWN_OPERATION", `unknown operation: ${envelope.operation}`));
      return;
    }

    const result = await Promise.race([operation(envelope.request, { binding }), timeout.promise]);
    writeEnvelope(res, 200, successEnvelope(envelope.operation, result));
  } catch (cause) {
    if (cause instanceof HostError) {
      const status = cause.code === "BRIDGE_TIMEOUT" ? 504 : cause.code === "PAYLOAD_TOO_LARGE" ? 413 : 502;
      if (cause.code === "PAYLOAD_TOO_LARGE" && !res.headersSent) {
        // The request body was only partially read — close the connection
        // after this response instead of returning it to a keep-alive pool,
        // where the unread trailing bytes would corrupt the next request.
        res.setHeader("Connection", "close");
      }
      writeEnvelope(res, status, errorEnvelope(null, cause.code, cause.message));
      return;
    }
    writeEnvelope(res, 500, errorEnvelope(null, "BRIDGE_UNAVAILABLE", cause instanceof Error ? cause.message : String(cause)));
  } finally {
    timeout.clear();
  }
}
