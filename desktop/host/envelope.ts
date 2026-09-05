/**
 * Shared envelope types + typed-error construction for the Desktop Host
 * contract, mirroring `Memory/docs/CONTRACTS.md`'s existing
 * `{contractVersion, operation, ok, result|error}` convention — the one
 * cross-engine precedent already established in this repository.
 */

import { CONTRACT_VERSION } from "./hostConfig.js";

export type ErrorCode =
  | "UNSUPPORTED_CONTRACT_VERSION"
  | "UNKNOWN_OPERATION"
  | "INVALID_REQUEST"
  | "INVALID_CURSOR"
  | "INVALID_FOCUS"
  | "INVALID_PROJECT_DESCRIPTOR"
  | "NOT_FOUND"
  | "BRIDGE_UNAVAILABLE"
  | "BRIDGE_TIMEOUT"
  | "BRIDGE_MALFORMED_OUTPUT"
  | "METHOD_NOT_ALLOWED"
  | "PAYLOAD_TOO_LARGE";

export interface HostRequestEnvelope {
  readonly contractVersion: number;
  readonly operation: string;
  readonly request: Record<string, unknown>;
}

export interface HostSuccessEnvelope {
  readonly contractVersion: number;
  readonly operation: string;
  readonly ok: true;
  readonly result: Record<string, unknown>;
}

export interface HostErrorEnvelope {
  readonly contractVersion: number;
  readonly operation: string | null;
  readonly ok: false;
  readonly error: { readonly code: ErrorCode; readonly message: string };
}

export type HostResponseEnvelope = HostSuccessEnvelope | HostErrorEnvelope;

export class HostError extends Error {
  readonly code: ErrorCode;

  constructor(code: ErrorCode, message: string) {
    super(message);
    this.name = "HostError";
    this.code = code;
  }
}

export function successEnvelope(operation: string, result: Record<string, unknown>): HostSuccessEnvelope {
  return { contractVersion: CONTRACT_VERSION, operation, ok: true, result };
}

export function errorEnvelope(operation: string | null, code: ErrorCode, message: string): HostErrorEnvelope {
  return { contractVersion: CONTRACT_VERSION, operation, ok: false, error: { code, message } };
}
