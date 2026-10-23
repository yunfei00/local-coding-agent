import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from "node:fs";
import os from "node:os";
import path from "node:path";
import {it, expect} from "vitest";
import {desktopArtifact} from "./desktopArtifact";

it("previews only bounded PNG artifacts, rejecting unrelated files and traversal", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "lca-preview-"));
  try {
    const dir = path.join(root, "desktop-artifacts", "turn_" + "a".repeat(32));
    mkdirSync(dir, {recursive:true});
    const file = path.join(dir, "capture_" + "b".repeat(32) + ".png");
    // Format/authorization unit fixture, never represented as desktop pixels.
    writeFileSync(file, Buffer.from([137,80,78,71,13,10,26,10]));
    expect(desktopArtifact(root, file)).toMatch(/^data:image\/png;base64,/);
    const other = path.join(root, "private.png");
    writeFileSync(other, "private");
    expect(() => desktopArtifact(root, other)).toThrow("directory");
    writeFileSync(file, "not PNG");
    expect(() => desktopArtifact(root, file)).toThrow("format");
    expect(() => desktopArtifact(root, null)).toThrow("reference");
  } finally { rmSync(root, {recursive:true, force:true}); }
});
