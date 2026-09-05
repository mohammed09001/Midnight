import { describe, expect, it, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ProjectDescriptorError, resolveProjectBinding } from "../../host/projectBinding";

function makeProjectRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "midnight-project-"));
  mkdirSync(join(root, "Performance", "data"), { recursive: true });
  return root;
}

function writeDescriptor(root: string, document: unknown): void {
  writeFileSync(join(root, "midnight.project.json"), JSON.stringify(document), "utf-8");
}

describe("resolveProjectBinding", () => {
  const roots: string[] = [];
  afterEach(() => {
    while (roots.length) {
      rmSync(roots.pop()!, { recursive: true, force: true });
    }
  });

  function root(): string {
    const created = makeProjectRoot();
    roots.push(created);
    return created;
  }

  it("resolves a valid descriptor by walking up from a nested start directory", () => {
    const projectRoot = root();
    writeDescriptor(projectRoot, {
      descriptorVersion: 1,
      projectId: "midnight",
      performanceDataDir: "Performance/data",
      workspaceId: null,
    });
    const nested = join(projectRoot, "desktop", "host");
    mkdirSync(nested, { recursive: true });

    const binding = resolveProjectBinding(nested);
    expect(binding.projectId).toBe("midnight");
    expect(binding.projectRoot).toBe(projectRoot);
    expect(binding.performanceDataDir).toBe(join(projectRoot, "Performance", "data"));
    expect(binding.workspaceId).toBeNull();
  });

  it("rejects a missing descriptor file", () => {
    const projectRoot = root();
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });

  it("rejects malformed JSON", () => {
    const projectRoot = root();
    writeFileSync(join(projectRoot, "midnight.project.json"), "{not-json", "utf-8");
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });

  it("rejects a descriptor missing a required field", () => {
    const projectRoot = root();
    writeDescriptor(projectRoot, { descriptorVersion: 1, projectId: "midnight" });
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });

  it("rejects an unknown extra field (additionalProperties: false)", () => {
    const projectRoot = root();
    writeDescriptor(projectRoot, {
      descriptorVersion: 1,
      projectId: "midnight",
      performanceDataDir: "Performance/data",
      somethingElse: true,
    });
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });

  it("rejects a performanceDataDir that escapes the project root", () => {
    const projectRoot = root();
    writeDescriptor(projectRoot, {
      descriptorVersion: 1,
      projectId: "midnight",
      performanceDataDir: "../outside",
      workspaceId: null,
    });
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });

  it("rejects descriptorVersion below 1", () => {
    const projectRoot = root();
    writeDescriptor(projectRoot, {
      descriptorVersion: 0,
      projectId: "midnight",
      performanceDataDir: "Performance/data",
    });
    expect(() => resolveProjectBinding(projectRoot)).toThrow(ProjectDescriptorError);
  });
});
