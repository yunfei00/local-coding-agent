import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, it } from "vitest";
import { isScopedResource, productionPermissions } from "./openCodePermissions";

it("checks actual paths and never grants arbitrary cross-project reads or writes", () => {
  const sandbox = mkdtempSync(path.join(os.tmpdir(),"lca-permissions-"));
  try {
    const project = path.join(sandbox,"project");
    const sibling = path.join(sandbox,"sibling");
    mkdirSync(project);
    mkdirSync(sibling);
    writeFileSync(path.join(project,"hello.txt"),"fixture");
    symlinkSync(sibling,path.join(project,"outside"),process.platform === "win32" ? "junction" : "dir");
    expect(isScopedResource(project,"hello.txt")).toBe(true);
    expect(isScopedResource(project,"new.txt")).toBe(true);
    expect(isScopedResource(project,"../sibling/content.txt")).toBe(false);
    expect(isScopedResource(project,path.join(sibling,"content.txt"))).toBe(false);
    expect(isScopedResource(project,"outside/content.txt")).toBe(false);
    expect(isScopedResource(project,".env.local")).toBe(false);
    expect(isScopedResource(project,".git/config")).toBe(false);
    for (const mode of ["workspace","read_only","full_access"] as const) {
      expect(productionPermissions(mode)).toContainEqual({action:"external_directory",resource:"*",effect:"deny"});
      expect(productionPermissions(mode)).toContainEqual({action:"read",resource:"*",effect:"ask"});
    }
  } finally {
    rmSync(sandbox,{recursive:true,force:true});
  }
});
