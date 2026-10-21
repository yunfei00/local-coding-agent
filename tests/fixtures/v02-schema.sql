-- Official v0.2.0 schema, source commit 9dd27dd (synthetic data only).
CREATE TABLE approvals (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                decision TEXT,
                risk TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );
CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                active_thread_id TEXT
            );
CREATE TABLE prompt_rules (
                rule_key TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                scope_id TEXT,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                active_model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
CREATE TABLE tool_calls (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                result_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
CREATE INDEX idx_messages_thread_id
            ON messages(thread_id, id);
CREATE INDEX idx_prompt_rules_scope
            ON prompt_rules(scope, scope_id);
CREATE INDEX idx_threads_project_updated
            ON threads(project_id, updated_at DESC);
PRAGMA user_version=2;
