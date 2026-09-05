/**
 * Resolves and validates the canonical Midnight project descriptor
 * (`midnight.project.json`). This is the "trusted host, not React" resolution
 * point required by Execution 03: it runs once at Host startup, never per
 * request, and never accepts a filesystem path from a caller — the only
 * input is the Host's own module location, used purely as the search origin.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { ContractValidationError, validate, loadSchema } from "./schemaValidator.js";

const DESCRIPTOR_FILENAME = "midnight.project.json";
const MAX_WALK_LEVELS = 32;

export class ProjectDescriptorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectDescriptorError";
  }
}

export interface ProjectBinding {
  readonly descriptorVersion: number;
  readonly projectId: string;
  /** Absolute path, guaranteed to resolve inside the project root. */
  readonly performanceDataDir: string;
  /** Absolute path to the directory containing `midnight.project.json`. */
  readonly projectRoot: string;
  readonly workspaceId: string | null;
}

function findDescriptorFile(startDir: string): string {
  let current = resolve(startDir);
  for (let level = 0; level < MAX_WALK_LEVELS; level += 1) {
    const candidate = join(current, DESCRIPTOR_FILENAME);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  throw new ProjectDescriptorError(`no ${DESCRIPTOR_FILENAME} found above ${startDir}`);
}

interface RawDescriptor {
  descriptorVersion: number;
  projectId: string;
  performanceDataDir: string;
  workspaceId?: string | null;
}

export function resolveProjectBinding(startDir: string): ProjectBinding {
  const descriptorPath = findDescriptorFile(startDir);

  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(descriptorPath, "utf-8"));
  } catch (cause) {
    throw new ProjectDescriptorError(`unreadable project descriptor: ${String(cause)}`);
  }

  const violations = validate(loadSchema("project-descriptor.schema.json"), raw);
  if (violations.length > 0) {
    throw new ProjectDescriptorError(new ContractValidationError("project-descriptor.schema.json", violations).message);
  }

  const document = raw as RawDescriptor;
  const projectRoot = resolve(dirname(descriptorPath));
  const resolvedDataDir = resolve(projectRoot, document.performanceDataDir);
  const relativeToRoot = relative(projectRoot, resolvedDataDir);
  if (relativeToRoot.startsWith("..") || isAbsolute(relativeToRoot)) {
    throw new ProjectDescriptorError(`performanceDataDir '${document.performanceDataDir}' escapes the project root`);
  }

  return {
    descriptorVersion: document.descriptorVersion,
    projectId: document.projectId,
    performanceDataDir: resolvedDataDir,
    projectRoot,
    workspaceId: document.workspaceId ?? null,
  };
}
