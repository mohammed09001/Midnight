/**
 * Minimal JSON Schema 2020-12 subset interpreter — the TypeScript twin of
 * `Performance/midnight_performance/contract_schema.py`. Both execute the
 * exact same `.schema.json` files (single source of truth under
 * `Performance/midnight_performance/schemas/`) rather than each hand-writing
 * an independent, possibly-drifting validator. Deliberately dependency-free
 * (no ajv) to match this repo's zero-runtime-dependency convention.
 *
 * Vocabulary supported: `type`, `required`, `properties`,
 * `additionalProperties: false`, `items`, `enum`, `const`, `minimum`/
 * `maximum`, `minLength`, and a single top-level `oneOf`. No `$ref`, no
 * nested `oneOf`/`allOf` — the four schemas in this package never need them.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT_MARKER = "midnight.project.json";
const MAX_WALK_LEVELS = 32;

/**
 * Locate the schemas directory by walking up from this module's own
 * location to the repo-root marker (`midnight.project.json`), rather than a
 * fixed relative "../.." — that offset would differ between running the
 * TypeScript source directly (tests) and running compiled output nested
 * under `host/dist/`, and this walk is correct either way.
 */
function findSchemasDir(): string {
  let current = resolve(dirname(fileURLToPath(import.meta.url)));
  for (let level = 0; level < MAX_WALK_LEVELS; level += 1) {
    const candidate = join(current, "Performance", "midnight_performance", "schemas");
    if (existsSync(join(current, REPO_ROOT_MARKER)) && existsSync(candidate)) {
      return candidate;
    }
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  throw new Error(`could not locate Performance/midnight_performance/schemas above ${dirname(fileURLToPath(import.meta.url))}`);
}

let cachedSchemasDir: string | null = null;
function schemasDir(): string {
  if (!cachedSchemasDir) cachedSchemasDir = findSchemasDir();
  return cachedSchemasDir;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type JsonSchema = any;
export type JsonValue = unknown;

export function loadSchema(name: string): JsonSchema {
  return JSON.parse(readFileSync(join(schemasDir(), name), "utf-8"));
}

function matchesType(instance: JsonValue, typeName: string): boolean {
  switch (typeName) {
    case "object":
      return typeof instance === "object" && instance !== null && !Array.isArray(instance);
    case "array":
      return Array.isArray(instance);
    case "string":
      return typeof instance === "string";
    case "boolean":
      return typeof instance === "boolean";
    case "integer":
      return typeof instance === "number" && Number.isInteger(instance);
    case "number":
      return typeof instance === "number";
    case "null":
      return instance === null;
    default:
      return false;
  }
}

export function validate(schema: JsonSchema, instance: JsonValue, path = "$"): string[] {
  if (schema.oneOf) {
    const branches: JsonSchema[] = schema.oneOf;
    const matches = branches.filter((branch) => validate(branch, instance, path).length === 0);
    if (matches.length === 1) return [];
    if (matches.length === 0) return [`${path}: matches none of the ${branches.length} allowed shapes`];
    return [`${path}: matches ${matches.length} allowed shapes, expected exactly one`];
  }

  const violations: string[] = [];

  if (schema.type !== undefined) {
    const typeNames: string[] = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!typeNames.some((name) => matchesType(instance, name))) {
      violations.push(
        `${path}: expected type ${JSON.stringify(schema.type)}, got ${instance === null ? "null" : typeof instance}`,
      );
      return violations; // further structural checks are meaningless on a type mismatch
    }
  }

  if (Object.prototype.hasOwnProperty.call(schema, "const") && instance !== schema.const) {
    violations.push(`${path}: expected constant value ${JSON.stringify(schema.const)}, got ${JSON.stringify(instance)}`);
  }

  if (Array.isArray(schema.enum) && !schema.enum.includes(instance)) {
    violations.push(`${path}: ${JSON.stringify(instance)} is not one of ${JSON.stringify(schema.enum)}`);
  }

  if (typeof instance === "string" && typeof schema.minLength === "number" && instance.length < schema.minLength) {
    violations.push(`${path}: string shorter than minLength ${schema.minLength}`);
  }

  if (typeof instance === "number") {
    if (typeof schema.minimum === "number" && instance < schema.minimum) {
      violations.push(`${path}: ${instance} is below minimum ${schema.minimum}`);
    }
    if (typeof schema.maximum === "number" && instance > schema.maximum) {
      violations.push(`${path}: ${instance} is above maximum ${schema.maximum}`);
    }
  }

  if (instance !== null && typeof instance === "object" && !Array.isArray(instance)) {
    const record = instance as Record<string, unknown>;
    const properties: Record<string, JsonSchema> = schema.properties ?? {};
    for (const key of schema.required ?? []) {
      if (!(key in record)) violations.push(`${path}: missing required property '${key}'`);
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(record)) {
        if (!(key in properties)) violations.push(`${path}: unexpected property '${key}'`);
      }
    }
    for (const [key, subschema] of Object.entries(properties)) {
      if (key in record) violations.push(...validate(subschema, record[key], `${path}.${key}`));
    }
  }

  if (Array.isArray(instance) && schema.items) {
    instance.forEach((item, index) => violations.push(...validate(schema.items, item, `${path}[${index}]`)));
  }

  return violations;
}

export class ContractValidationError extends Error {
  readonly schemaName: string;
  readonly violations: readonly string[];

  constructor(schemaName: string, violations: readonly string[]) {
    super(`${schemaName}: ${violations.join("; ")}`);
    this.name = "ContractValidationError";
    this.schemaName = schemaName;
    this.violations = violations;
  }
}

export function validateOrThrow(schemaName: string, instance: JsonValue): void {
  const schema = loadSchema(schemaName);
  const violations = validate(schema, instance);
  if (violations.length > 0) {
    throw new ContractValidationError(schemaName, violations);
  }
}
