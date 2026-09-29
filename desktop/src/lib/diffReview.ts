export type DiffFileLike = {
  path: string;
  status?: string;
  binary?: boolean;
  truncated?: boolean;
};

export function diffStatusLabel(status?: string): string {
  switch (status) {
    case "added":
      return "A";
    case "deleted":
      return "D";
    case "renamed":
      return "R";
    case "untracked":
      return "U";
    default:
      return "M";
  }
}

export function resolveSelectedDiffPath(
  files: DiffFileLike[],
  currentPath: string | null | undefined
): string {
  if (
    currentPath &&
    files.some((file) => file.path === currentPath)
  ) {
    return currentPath;
  }
  return files[0]?.path ?? "";
}

export function diffPreviewState(file: DiffFileLike): string[] {
  const state: string[] = [];
  if (file.binary) {
    state.push("binary");
  }
  if (file.truncated) {
    state.push("truncated");
  }
  return state;
}
