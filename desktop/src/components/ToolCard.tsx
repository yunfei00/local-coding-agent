import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";

import {
  diffPreviewState,
  diffStatusLabel,
  resolveSelectedDiffPath
} from "../lib/diffReview";
import { OrderedToolChunk } from "../lib/toolStream";

export type ToolChunk = OrderedToolChunk;

export type DiffLine = {
  type: "add" | "delete" | "context" | "meta";
  content: string;
  old_line?: number | null;
  new_line?: number | null;
};

export type DiffHunk = {
  header: string;
  lines: DiffLine[];
};

export type DiffFile = {
  path: string;
  old_path?: string;
  new_path?: string;
  status?: string;
  binary?: boolean;
  additions?: number;
  deletions?: number;
  truncated?: boolean;
  similarity?: number | null;
  hunk_count?: number;
  preview_line_count?: number;
  hunks?: DiffHunk[];
};

export type DiffReviewMeta = {
  read_only?: boolean;
  mode?: "working_tree" | "staged" | string;
  complete_preview?: boolean;
  status_counts?: Record<string, number>;
  truncated_files?: string[];
  binary_files?: string[];
  renamed_files?: Array<{
    old_path?: string;
    new_path?: string;
    similarity?: number | null;
  }>;
  preview_files_truncated?: boolean;
  path_filter?: string | null;
};

export type ToolView = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status:
    | "requested"
    | "running"
    | "stopping"
    | "completed"
    | "failed"
    | "cancelled"
    | "timed_out";
  summary?: string;
  chunks: ToolChunk[];
  pid?: number;
  cwd?: string;
  command?: string;
  exitCode?: number;
  durationMs?: number;
  diffFiles?: DiffFile[];
  diffReview?: DiffReviewMeta;
  additions?: number;
  deletions?: number;
  streamTruncated?: boolean;
  droppedOutputChars?: number;
  terminationReason?: string;
  terminationMethod?: string;
  lastSequence?: number;
};

function formatDuration(durationMs?: number): string {
  if (durationMs === undefined) {
    return "";
  }
  if (durationMs < 1000) {
    return durationMs + " ms";
  }
  return (durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0) + " s";
}

function statusLabel(tool: ToolView): string {
  if (tool.status === "running") {
    return "Running";
  }
  if (tool.status === "stopping") {
    return "Stopping…";
  }
  if (tool.status === "cancelled") {
    return "Stopped";
  }
  if (tool.status === "timed_out") {
    return "Timed out";
  }
  if (tool.status === "failed") {
    return "Failed";
  }
  if (tool.status === "completed") {
    return tool.exitCode === undefined || tool.exitCode === 0
      ? "Completed"
      : "Exit " + tool.exitCode;
  }
  return "Queued";
}

function TerminalCard({ tool }: { tool: ToolView }) {
  const outputRef = useRef<HTMLPreElement | null>(null);

  useLayoutEffect(() => {
    const element = outputRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }, [tool.chunks]);

  return (
    <div className={"tool-card terminal-card tool-" + tool.status}>
      <div className="tool-card-header">
        <div>
          <span className="tool-kind">TERMINAL</span>
          <strong>{statusLabel(tool)}</strong>
        </div>
        <div className="tool-meta">
          {tool.pid ? <span>PID {tool.pid}</span> : null}
          {tool.streamTruncated ? <span>Output limited</span> : null}
          {tool.durationMs !== undefined ? (
            <span>{formatDuration(tool.durationMs)}</span>
          ) : null}
        </div>
      </div>

      <div className="terminal-command">
        <span>$</span>
        <code>{tool.command ?? String(tool.arguments.command ?? "")}</code>
      </div>

      {tool.cwd ? <div className="terminal-cwd">{tool.cwd}</div> : null}

      {tool.chunks.length ? (
        <pre ref={outputRef} className="terminal-output">
          {tool.chunks.map((chunk) => (
            <span
              key={chunk.sequence}
              className={
                chunk.stream === "stderr"
                  ? "terminal-stderr"
                  : "terminal-stdout"
              }
            >
              {chunk.text}
            </span>
          ))}
        </pre>
      ) : tool.status === "running" ? (
        <div className="terminal-empty">Waiting for output…</div>
      ) : null}

      {tool.streamTruncated || (tool.droppedOutputChars ?? 0) > 0 ? (
        <div className="terminal-truncated">
          Live output was limited to keep the desktop responsive.
          {(tool.droppedOutputChars ?? 0) > 0
            ? " Older rendered output was dropped."
            : ""}
        </div>
      ) : null}

      {tool.terminationReason ? (
        <div className="terminal-termination">
          Process tree {tool.status === "stopping" ? "is stopping" : "stopped"}
          {" · " + tool.terminationReason}
          {tool.terminationMethod ? " · " + tool.terminationMethod : ""}
        </div>
      ) : null}

      {tool.summary ? (
        <div className="tool-summary">{tool.summary}</div>
      ) : null}
    </div>
  );
}

function DiffLineRow({ line }: { line: DiffLine }) {
  const marker =
    line.type === "add"
      ? "+"
      : line.type === "delete"
        ? "-"
        : line.type === "meta"
          ? ""
          : " ";

  return (
    <div className={"diff-line diff-line-" + line.type}>
      <span className="diff-line-number">
        {line.old_line ?? ""}
      </span>
      <span className="diff-line-number">
        {line.new_line ?? ""}
      </span>
      <span className="diff-marker">{marker}</span>
      <code>{line.content}</code>
    </div>
  );
}

function DiffReview({ tool }: { tool: ToolView }) {
  const files = tool.diffFiles ?? [];
  const review = tool.diffReview;
  const [selectedPath, setSelectedPath] = useState(() =>
    resolveSelectedDiffPath(files, null)
  );

  useEffect(() => {
    setSelectedPath((current) =>
      resolveSelectedDiffPath(files, current)
    );
  }, [files]);

  const selectedFile = useMemo(
    () =>
      files.find((file) => file.path === selectedPath) ??
      files[0],
    [files, selectedPath]
  );

  const statusCounts = Object.entries(review?.status_counts ?? {}).filter(
    ([, count]) => count > 0
  );

  return (
    <div className={"tool-card diff-card tool-" + tool.status}>
      <div className="tool-card-header">
        <div>
          <span className="tool-kind">REVIEW</span>
          <strong>
            {files.length} file{files.length === 1 ? "" : "s"}
          </strong>
          <span className="diff-readonly">Read only</span>
          {review?.complete_preview === false ? (
            <span className="diff-partial">Partial preview</span>
          ) : files.length > 0 ? (
            <span className="diff-complete">Review ready</span>
          ) : null}
        </div>
        <div className="diff-totals">
          <span className="diff-plus">+{tool.additions ?? 0}</span>
          <span className="diff-minus">-{tool.deletions ?? 0}</span>
        </div>
      </div>

      {files.length === 0 ? (
        <div className="diff-empty">No changes in this diff.</div>
      ) : (
        <>
          <div className="diff-review-toolbar">
            <span>
              {review?.mode === "staged" ? "Staged" : "Working tree"}
            </span>
            {statusCounts.map(([status, count]) => (
              <span key={status}>
                {diffStatusLabel(status)} {count}
              </span>
            ))}
            {(review?.binary_files?.length ?? 0) > 0 ? (
              <span>{review?.binary_files?.length} binary</span>
            ) : null}
            {(review?.truncated_files?.length ?? 0) > 0 ? (
              <span>{review?.truncated_files?.length} limited</span>
            ) : null}
          </div>

          <div className="diff-review-layout">
            <aside className="diff-file-list" aria-label="Changed files">
              {files.map((file, fileIndex) => {
                const states = diffPreviewState(file);
                const active = file.path === selectedFile?.path;
                return (
                  <button
                    type="button"
                    className={
                      "diff-file-button" + (active ? " active" : "")
                    }
                    key={file.path + ":" + fileIndex}
                    onClick={() => setSelectedPath(file.path)}
                  >
                    <span
                      className={
                        "diff-status-badge diff-status-" +
                        (file.status ?? "modified")
                      }
                    >
                      {diffStatusLabel(file.status)}
                    </span>
                    <span className="diff-file-button-main">
                      <span className="diff-file-path">{file.path}</span>
                      {file.status === "renamed" && file.old_path ? (
                        <span className="diff-file-origin">
                          from {file.old_path}
                        </span>
                      ) : null}
                    </span>
                    <span className="diff-file-stats">
                      <span className="diff-plus">
                        +{file.additions ?? 0}
                      </span>
                      <span className="diff-minus">
                        -{file.deletions ?? 0}
                      </span>
                    </span>
                    {states.length ? (
                      <span className="diff-file-flags">
                        {states.join(" · ")}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </aside>

            <section className="diff-preview">
              {selectedFile ? (
                <>
                  <div className="diff-preview-header">
                    <div>
                      <strong>{selectedFile.path}</strong>
                      <span>
                        {selectedFile.status ?? "modified"}
                        {selectedFile.similarity !== null &&
                        selectedFile.similarity !== undefined
                          ? " · " + selectedFile.similarity + "% similarity"
                          : ""}
                      </span>
                    </div>
                    <div className="diff-file-stats">
                      <span className="diff-plus">
                        +{selectedFile.additions ?? 0}
                      </span>
                      <span className="diff-minus">
                        -{selectedFile.deletions ?? 0}
                      </span>
                    </div>
                  </div>

                  {selectedFile.status === "renamed" &&
                  selectedFile.old_path &&
                  selectedFile.new_path ? (
                    <div className="diff-rename">
                      <code>{selectedFile.old_path}</code>
                      <span>→</span>
                      <code>{selectedFile.new_path}</code>
                    </div>
                  ) : null}

                  {selectedFile.binary ? (
                    <div className="diff-binary">
                      Binary file changed. Text patch preview is unavailable.
                    </div>
                  ) : (selectedFile.hunks ?? []).length === 0 ? (
                    <div className="diff-empty">
                      No textual patch for this file.
                    </div>
                  ) : (
                    <div className="diff-hunks">
                      {(selectedFile.hunks ?? []).map((hunk, hunkIndex) => (
                        <div
                          className="diff-hunk"
                          key={hunk.header + ":" + hunkIndex}
                        >
                          <div className="diff-hunk-header">
                            {hunk.header}
                          </div>
                          {hunk.lines.map((line, lineIndex) => (
                            <DiffLineRow
                              key={hunkIndex + ":" + lineIndex}
                              line={line}
                            />
                          ))}
                        </div>
                      ))}
                    </div>
                  )}

                  {selectedFile.truncated ? (
                    <div className="diff-truncated">
                      This file preview was truncated for UI safety. Git
                      statistics still describe the full detected change.
                    </div>
                  ) : null}
                </>
              ) : null}
            </section>
          </div>
        </>
      )}

      {tool.summary ? (
        <div className="tool-summary">{tool.summary}</div>
      ) : null}
    </div>
  );
}

function GenericToolCard({ tool }: { tool: ToolView }) {
  return (
    <div className={"tool-card generic-tool-card tool-" + tool.status}>
      <div className="tool-card-header">
        <div>
          <span className="tool-kind">TOOL</span>
          <strong>{tool.name}</strong>
        </div>
        <span>{statusLabel(tool)}</span>
      </div>
      <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
      {tool.summary ? (
        <div className="tool-summary">{tool.summary}</div>
      ) : null}
    </div>
  );
}

export function ToolCard({ tool }: { tool: ToolView }) {
  if (tool.name === "run_command") {
    return <TerminalCard tool={tool} />;
  }
  if (tool.name === "git_diff" && tool.diffFiles) {
    return <DiffReview tool={tool} />;
  }
  return <GenericToolCard tool={tool} />;
}
