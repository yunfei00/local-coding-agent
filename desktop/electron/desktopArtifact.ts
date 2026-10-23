import {readFileSync, realpathSync, statSync} from "node:fs";
import path from "node:path";

/** Local review only. Never accept an arbitrary renderer-supplied file path. */
export function desktopArtifact(dataRoot: string, candidate: unknown): string {
  if (typeof candidate !== "string") throw new Error("Invalid screenshot reference");
  const root = realpathSync(path.join(dataRoot, "desktop-artifacts"));
  const target = realpathSync(candidate);
  const relative = path.relative(root, target);
  if (!/^turn_[a-f0-9]{32}[\\/]capture_[a-f0-9]{32}\.png$/.test(relative))
    throw new Error("Screenshot must belong to the local artifact directory");
  const info = statSync(target);
  if (!info.isFile() || info.size > 32 * 1024 * 1024) throw new Error("Invalid screenshot size");
  const data = readFileSync(target);
  if (!data.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])))
    throw new Error("Invalid screenshot format");
  return "data:image/png;base64," + data.toString("base64");
}
