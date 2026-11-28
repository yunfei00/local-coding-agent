export type OpenCodePermissionMode = "read_only" | "workspace" | "full_access";
export type OpenCodePermission = { action: string; resource: string; effect: "allow" | "ask" | "deny" };

export function productionPermissions(mode: OpenCodePermissionMode): OpenCodePermission[] {
  const rule = (action: string, effect: OpenCodePermission["effect"]): OpenCodePermission =>
    ({ action, resource: "*", effect });
  const rules = [
    rule("*", "deny"),
    ...["read", "glob", "grep", "list"].map(action => rule(action, "allow")),
  ];
  if (mode === "workspace" || mode === "full_access") {
    rules.push(rule("edit", mode === "full_access" ? "allow" : "ask"), rule("shell", "ask"));
  }
  return rules;
}
