export type ToolChunk = {
  stream: "stdout" | "stderr";
  text: string;
};

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
  hunks?: DiffHunk[];
};

export type ToolView = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "requested" | "running" | "completed" | "failed";
  summary?: string;
  chunks: ToolChunk[];
  pid?: number;
  cwd?: string;
  command?: string;
  exitCode?: number;
  durationMs?: number;
  diffFiles?: DiffFile[];
  additions?: number;
  deletions?: number;
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
  return (
    <div className={"tool-card terminal-card tool-" + tool.status}>
      <div className="tool-card-header">
        <div>
          <span className="tool-kind">TERMINAL</span>
          <strong>{statusLabel(tool)}</strong>
        </div>
        <div className="tool-meta">
          {tool.pid ? <span>PID {tool.pid}</span> : null}
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
        <pre className="terminal-output">
          {tool.chunks.map((chunk, index) => (
            <span
              key={index}
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
  return (
    <div className={"tool-card diff-card tool-" + tool.status}>
      <div className="tool-card-header">
        <div>
          <span className="tool-kind">DIFF</span>
          <strong>
            {files.length} file{files.length === 1 ? "" : "s"}
          </strong>
        </div>
        <div className="diff-totals">
          <span className="diff-plus">+{tool.additions ?? 0}</span>
          <span className="diff-minus">-{tool.deletions ?? 0}</span>
        </div>
      </div>

      {files.length === 0 ? (
        <div className="diff-empty">No changes in this diff.</div>
      ) : (
        <div className="diff-files">
          {files.map((file, fileIndex) => (
            <details
              className="diff-file"
              key={file.path + ":" + fileIndex}
              open={fileIndex < 4}
            >
              <summary>
                <span className="diff-file-path">{file.path}</span>
                <span className="diff-file-status">
                  {file.status ?? "modified"}
                </span>
                <span className="diff-file-stats">
                  <span className="diff-plus">
                    +{file.additions ?? 0}
                  </span>
                  <span className="diff-minus">
                    -{file.deletions ?? 0}
                  </span>
                </span>
              </summary>

              {file.binary ? (
                <div className="diff-binary">Binary file changed.</div>
              ) : (
                <div className="diff-hunks">
                  {(file.hunks ?? []).map((hunk, hunkIndex) => (
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
                  {file.truncated ? (
                    <div className="diff-truncated">
                      Diff preview truncated for UI safety.
                    </div>
                  ) : null}
                </div>
              )}
            </details>
          ))}
        </div>
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
