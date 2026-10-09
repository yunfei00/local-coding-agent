import { useEffect, useMemo, useState } from "react";

type GitStatus = {
  branch?: string | null;
  detached?: boolean;
  staged?: string[];
  unstaged?: string[];
  untracked?: string[];
  staged_count?: number;
  unstaged_count?: number;
  untracked_count?: number;
  clean?: boolean;
};

type GitBranch = {
  name: string;
  sha?: string;
  upstream?: string | null;
  current?: boolean;
};

type GitWorktree = {
  path: string;
  head?: string;
  branch?: string;
  detached?: boolean;
  bare?: boolean;
  locked?: boolean | string;
  prunable?: boolean | string;
  managed?: boolean;
  current?: boolean;
};

type GitOverview = {
  project_id?: string;
  project_path?: string;
  status?: GitStatus;
  branches?: {
    current_branch?: string | null;
    branches?: GitBranch[];
  };
  worktrees?: {
    worktrees?: GitWorktree[];
  };
  errors?: Array<{ tool?: string; message?: string }>;
};

function readOverview(event: AgentEnvelope): GitOverview {
  return (event.payload ?? {}) as GitOverview;
}

function FileList({
  title,
  items
}: {
  title: string;
  items: string[];
}) {
  return (
    <section className="git-file-group">
      <div className="git-file-group-title">
        <strong>{title}</strong>
        <span>{items.length}</span>
      </div>
      {items.length ? (
        <div className="git-file-group-list">
          {items.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </div>
      ) : (
        <div className="git-empty-small">None</div>
      )}
    </section>
  );
}

export function GitPanel({
  projectName,
  selectedModel,
  running,
  onProjectOpened,
  onClose
}: {
  projectName?: string;
  selectedModel?: string;
  running: boolean;
  onProjectOpened: (event: AgentEnvelope) => void;
  onClose: () => void;
}) {
  const [overview, setOverview] = useState<GitOverview>({});
  const [busy, setBusy] = useState(false);
  const [openingPath, setOpeningPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.getGitOverview();
      setOverview(readOverview(event));
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, [projectName]);

  const status = overview.status ?? {};
  const branches = overview.branches?.branches ?? [];
  const worktrees = overview.worktrees?.worktrees ?? [];
  const errors = overview.errors ?? [];

  const sourceWorktree = useMemo(
    () => worktrees.find((item) => !item.managed) ?? null,
    [worktrees]
  );

  const openWorktree = async (path: string) => {
    if (running || busy || openingPath) {
      return;
    }
    setOpeningPath(path);
    setError(null);
    try {
      const event = await window.localAgent.openManagedWorktree(
        path,
        selectedModel || undefined
      );
      onProjectOpened(event);
      onClose();
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setOpeningPath(null);
    }
  };

  return (
    <div className="git-overlay" role="dialog" aria-modal="true">
      <div className="git-panel">
        <header className="git-panel-header">
          <div>
            <span className="eyebrow">GIT WORKFLOW</span>
            <h2>{projectName ?? "Workspace"}</h2>
            <p>
              Review branch and working-tree state. Commit and push remain
              explicit-request + approval operations.
            </p>
          </div>
          <div className="settings-inline-actions">
            <button
              type="button"
              className="settings-secondary"
              disabled={busy || running}
              onClick={() => void load()}
            >
              {busy ? "Refreshing…" : "Refresh"}
            </button>
            <button type="button" className="panel-close" onClick={onClose}>
              Close
            </button>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {errors.length ? (
          <div className="settings-warning">
            {errors.map((item, index) => (
              <div key={(item.tool ?? "git") + ":" + index}>
                <strong>{item.tool ?? "Git"}</strong>
                <span>{item.message ?? "Git operation failed."}</span>
              </div>
            ))}
          </div>
        ) : null}

        <section className="git-summary-grid">
          <div>
            <span>Branch</span>
            <strong>{status.branch ?? (status.detached ? "Detached" : "—")}</strong>
          </div>
          <div>
            <span>Staged</span>
            <strong>{status.staged_count ?? 0}</strong>
          </div>
          <div>
            <span>Unstaged</span>
            <strong>{status.unstaged_count ?? 0}</strong>
          </div>
          <div>
            <span>Untracked</span>
            <strong>{status.untracked_count ?? 0}</strong>
          </div>
        </section>

        <section className="git-section">
          <div className="git-section-heading">
            <div>
              <h3>Working tree</h3>
              <p>
                Stage/unstage are available to the Agent in Workspace or Full
                Access mode.
              </p>
            </div>
            <span className={"git-clean-badge " + (status.clean ? "clean" : "dirty")}>
              {status.clean ? "Clean" : "Changes"}
            </span>
          </div>
          <div className="git-file-grid">
            <FileList title="Staged" items={status.staged ?? []} />
            <FileList title="Unstaged" items={status.unstaged ?? []} />
            <FileList title="Untracked" items={status.untracked ?? []} />
          </div>
        </section>

        <section className="git-section">
          <div className="git-section-heading">
            <div>
              <h3>Local branches</h3>
              <p>Current branch is marked below.</p>
            </div>
          </div>
          <div className="git-branch-list">
            {branches.length ? (
              branches.map((branch) => (
                <div
                  key={branch.name}
                  className={"git-branch-row" + (branch.current ? " current" : "")}
                >
                  <div>
                    <strong>{branch.name}</strong>
                    <small>{branch.sha ?? ""}</small>
                  </div>
                  <span>
                    {branch.current
                      ? "Current"
                      : branch.upstream
                        ? branch.upstream
                        : "Local"}
                  </span>
                </div>
              ))
            ) : (
              <div className="git-empty-small">No local branches found.</div>
            )}
          </div>
        </section>

        <section className="git-section">
          <div className="git-section-heading">
            <div>
              <h3>Worktrees</h3>
              <p>
                Task worktrees created by Local Coding Agent live outside the
                source working tree.
              </p>
            </div>
          </div>

          {sourceWorktree ? (
            <div className="git-source-worktree">
              <span>Source worktree</span>
              <code>{sourceWorktree.path}</code>
            </div>
          ) : null}

          <div className="git-worktree-list">
            {worktrees.length ? (
              worktrees.map((item) => (
                <div
                  key={item.path}
                  className={
                    "git-worktree-row" +
                    (item.current ? " current" : "") +
                    (item.managed ? " managed" : "")
                  }
                >
                  <div className="git-worktree-copy">
                    <div>
                      <strong>
                        {item.branch ??
                          (item.detached ? "Detached HEAD" : "Worktree")}
                      </strong>
                      {item.current ? <span>Current</span> : null}
                      {item.managed ? <span>Managed</span> : null}
                    </div>
                    <code title={item.path}>{item.path}</code>
                  </div>
                  {item.managed && !item.current ? (
                    <button
                      type="button"
                      disabled={running || busy || openingPath !== null}
                      onClick={() => void openWorktree(item.path)}
                    >
                      {openingPath === item.path ? "Opening…" : "Open"}
                    </button>
                  ) : null}
                </div>
              ))
            ) : (
              <div className="git-empty-small">No worktrees found.</div>
            )}
          </div>
        </section>

        <div className="git-safety-note">
          <strong>Git safety</strong>
          <p>
            Stage/unstage can modify Git index state in Workspace mode.
            Commit, push and task-worktree creation/removal still require an
            explicit current-user request; commit/push also require approval.
          </p>
        </div>
      </div>
    </div>
  );
}
