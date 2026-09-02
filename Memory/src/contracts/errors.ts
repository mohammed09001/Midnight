/**
 * Typed error surface for the Library Memory Engine.
 *
 * Failure behavior is explicit: the engine never silently degrades to an
 * in-memory mode or swallows persistence errors. Every material failure is
 * a typed error carrying a stable machine-readable code so terminal/tool
 * callers and sibling engines can react without string matching.
 */
import type { MemoryErrorCode } from "./types.ts";

export type { MemoryErrorCode };

export class MemoryEngineError extends Error {
  readonly code: MemoryErrorCode;

  constructor(code: MemoryErrorCode, message: string, options?: { cause?: unknown }) {
    super(message);
    this.name = "MemoryEngineError";
    this.code = code;
    if (options?.cause !== undefined) {
      this.cause = options.cause;
    }
  }
}

export class StoreUnavailableError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_STORE_UNAVAILABLE", message, options);
    this.name = "StoreUnavailableError";
  }
}

export class MigrationError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_MIGRATION_FAILED", message, options);
    this.name = "MigrationError";
  }
}

export class ValidationError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_VALIDATION_FAILED", message, options);
    this.name = "ValidationError";
  }
}

/**
 * Raised when a caller attempts to persist or embed secret-class material.
 * Secrets belong to the secure credential layer, never in Memory records.
 */
export class PrivacyViolationError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_PRIVACY_VIOLATION", message, options);
    this.name = "PrivacyViolationError";
  }
}

export class NotFoundError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_NOT_FOUND", message, options);
    this.name = "NotFoundError";
  }
}

export class ConflictError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_CONFLICT", message, options);
    this.name = "ConflictError";
  }
}

export class ContractMismatchError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_CONTRACT_MISMATCH", message, options);
    this.name = "ContractMismatchError";
  }
}

/**
 * Raised when a caller that is not authorized by the scope's intake policy
 * tries to propose a candidate (Task 8).
 */
export class IntakeUnauthorizedError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_INTAKE_UNAUTHORIZED", message, options);
    this.name = "IntakeUnauthorizedError";
  }
}

/**
 * Raised when promotion would violate a promotion policy — notably an
 * agent attempting to promote (AI cannot self-promote, Task 9).
 */
export class PromotionForbiddenError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_PROMOTION_FORBIDDEN", message, options);
    this.name = "PromotionForbiddenError";
  }
}

/**
 * Raised when a correction (direct revision) is attempted by an actor that
 * is not a user or authorized engine — agents correct via the candidate
 * intake instead (Task 12).
 */
export class CorrectionForbiddenError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_CORRECTION_FORBIDDEN", message, options);
    this.name = "CorrectionForbiddenError";
  }
}

/**
 * Raised when a mutation is refused by the scope's mutation policy
 * (Task 35): under a `restricted` policy, promote/revise/delete and other
 * mutations require explicit project/user authorization (an actor in the
 * policy's allow list) — agent-initiated mutations are never implicitly
 * allowed.
 */
export class MutationForbiddenError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_MUTATION_FORBIDDEN", message, options);
    this.name = "MutationForbiddenError";
  }
}

/**
 * Raised when a semantic operation is requested but no embedding provider has
 * been configured (Task 23). Memory functions fully without embeddings; this
 * signals the optional projection is simply not available.
 */
export class EmbeddingsUnavailableError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_EMBEDDINGS_UNAVAILABLE", message, options);
    this.name = "EmbeddingsUnavailableError";
  }
}

/**
 * Raised when a semantic operation is requested against a scope whose
 * embedding projection has not been built yet (Task 23). Build it first
 * (or rebuild after a model change).
 */
export class EmbeddingsNotBuiltError extends MemoryEngineError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("MEMORY_EMBEDDINGS_NOT_BUILT", message, options);
    this.name = "EmbeddingsNotBuiltError";
  }
}
