/**
 * Midnight Memory Engine — public contract identity.
 *
 * The contract version governs the engine's public API surface, its event
 * vocabulary, and the canonical record schema shape exposed to callers
 * (sibling engines, CLI users, agents). Breaking changes bump the major.
 */
export const MEMORY_ENGINE_ID = "midnight.memory-engine" as const;

export const MEMORY_ENGINE_CONTRACT_VERSION = "1.27.0" as const;

export type ContractVersion = typeof MEMORY_ENGINE_CONTRACT_VERSION;
