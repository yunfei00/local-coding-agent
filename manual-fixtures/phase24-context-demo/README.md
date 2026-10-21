# Phase 24 Context Demo

This is the fixed manual-validation workspace for Local Coding Agent v0.3 Phase 24.

Open **this folder itself** as the Local Coding Agent workspace:

```text
manual-fixtures/phase24-context-demo
```

Expected repository-map content:

- Python: `src/app.py`
- TypeScript: `src/service.ts`
- C++: `native/engine.cpp`
- Java: `java/Main.java`
- Kotlin: `kotlin/App.kt`
- Tests: `tests/test_app.py`
- Config: `pyproject.toml`, `package.json`

Recommended Pin file:

```text
src/version_info.py
```

Expected values:

```text
DEMO_APP_VERSION = "24.1"
DEMO_PROTOCOL = "context-demo"
```

Run `setup_ignored_dirs.ps1` once before validation to create local ignored trees.
