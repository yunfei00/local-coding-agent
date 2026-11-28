import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";

export type OpenCodePermissionMode = "read_only" | "workspace" | "full_access";
export type OpenCodePermission = { action: string; resource: string; effect: "allow" | "ask" | "deny" };

export function productionPermissions(mode: OpenCodePermissionMode): OpenCodePermission[] {
  const rule = (action: string, effect: OpenCodePermission["effect"]): OpenCodePermission =>
    ({ action, resource: "*", effect });
  const rules = [
    rule("*", "deny"),
    rule("external_directory", "deny"),
    ...["read", "glob", "grep"].map(action => rule(action, "ask")),
  ];
  if (mode === "workspace" || mode === "full_access") {
    rules.push(rule("edit", "ask"), rule("shell", "ask"));
  }
  return rules;
}
function contains(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(".." + path.sep));
}

export function isScopedResource(project: string, resource: unknown): boolean {
  if (typeof resource !== "string" || !resource || resource.length > 2000 || /[\0*?]/.test(resource)) return false;
  if (resource.slice(path.parse(resource).root.length).includes(":")) return false;
  let candidate = path.resolve(project, resource);
  if (!contains(project, candidate)) return false;
  const secretName = /^(?:\.git|\.ssh|\.env(?:\..*)?|\.npmrc|(?:provider|model|mcp)-secrets\.json|id_(?:rsa|ed25519))$/i;
  if (path.relative(project, candidate).split(path.sep).some(segment => secretName.test(segment))) return false;
  try {
    const root = realpathSync.native(project);
    for (;;) {
      try {
        const actual = realpathSync.native(candidate);
        return contains(root, actual) && !path.relative(root, actual).split(path.sep).some(segment => secretName.test(segment));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") return false;
        if (lstatSync(candidate, {throwIfNoEntry:false})?.isSymbolicLink()) return false;
        const parent = path.dirname(candidate);
        if (parent === candidate) return false;
        candidate = parent;
      }
    }
  } catch {
    return false;
  }
}
