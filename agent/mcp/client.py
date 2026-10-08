from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Literal, TextIO

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


MCPTransport = Literal["stdio", "streamable_http"]
MAX_LIST_PAGES = 100


class MCPClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: MCPTransport
    server_id: str | None = None
    trusted: bool = False
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    env: dict[str, str] | None = None
    timeout_seconds: float = 30.0

    def validate(self) -> "MCPServerConfig":
        name = self.name.strip()
        if not name:
            raise ValueError("MCP server name cannot be empty.")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("MCP timeout_seconds must be between 0 and 300.")

        if self.transport == "stdio":
            if not (self.command or "").strip():
                raise ValueError("stdio MCP server requires command.")
            if self.url:
                raise ValueError("stdio MCP server cannot define url.")
        elif self.transport == "streamable_http":
            if not (self.url or "").strip():
                raise ValueError("Streamable HTTP MCP server requires url.")
            if not str(self.url).startswith(("http://", "https://")):
                raise ValueError("MCP server url must use http or https.")
            if self.command:
                raise ValueError(
                    "Streamable HTTP MCP server cannot define command."
                )
        else:
            raise ValueError(f"Unsupported MCP transport: {self.transport}")
        return self


@dataclass(frozen=True)
class MCPToolDescriptor:
    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only_hint: bool = False
    destructive_hint: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MCPResourceDescriptor:
    server_name: str
    uri: str
    name: str
    description: str | None
    mime_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MCPServerStatus:
    name: str
    transport: MCPTransport
    connected: bool
    effective_command: str | None = None
    protocol_version: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Connection:
    config: MCPServerConfig
    client: Client
    status: MCPServerStatus


def _model_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _model_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_model_dict(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _bounded_payload(value: Any, max_chars: int) -> dict[str, Any]:
    normalized = _model_dict(value)
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(serialized) <= max_chars:
        return {
            "truncated": False,
            "value": normalized,
            "chars": len(serialized),
        }
    return {
        "truncated": True,
        "preview": serialized[:max_chars],
        "chars": len(serialized),
    }


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return schema if isinstance(schema, dict) else {"type": "object"}


class MCPClientManager:
    def __init__(
        self,
        configs: list[MCPServerConfig] | tuple[MCPServerConfig, ...] = (),
        *,
        max_output_chars: int = 64_000,
    ) -> None:
        if max_output_chars < 1024:
            raise ValueError("max_output_chars must be at least 1024.")
        self.max_output_chars = max_output_chars
        self._configs: dict[str, MCPServerConfig] = {}
        self._connections: dict[str, _Connection] = {}
        self._statuses: dict[str, MCPServerStatus] = {}
        self._stderr_logs: dict[str, TextIO] = {}

        for config in configs:
            self.add_config(config)

    @property
    def server_names(self) -> list[str]:
        return sorted(self._configs)

    def add_config(self, config: MCPServerConfig) -> None:
        config.validate()
        if config.name in self._configs:
            raise ValueError(f"Duplicate MCP server name: {config.name}")
        self._configs[config.name] = config
        self._statuses[config.name] = MCPServerStatus(
            name=config.name,
            transport=config.transport,
            connected=False,
        )

    def status(self, name: str) -> MCPServerStatus:
        status = self._statuses.get(name)
        if not status:
            raise MCPClientError(
                "MCP_SERVER_NOT_FOUND",
                f"Unknown MCP server: {name}",
            )
        return status

    def statuses(self) -> list[MCPServerStatus]:
        return [self._statuses[name] for name in self.server_names]

    def _config(self, name: str) -> MCPServerConfig:
        config = self._configs.get(name)
        if not config:
            raise MCPClientError(
                "MCP_SERVER_NOT_FOUND",
                f"Unknown MCP server: {name}",
            )
        return config

    def _stdio_error_text(
        self,
        config: MCPServerConfig,
    ) -> str:
        log = self._stderr_logs.get(config.name)
        if log is None:
            return ""
        try:
            log.flush()
            log.seek(0)
            text = log.read()[-8_000:].strip()
            log.seek(0, os.SEEK_END)
        except Exception:
            text = ""
        for value in (config.env or {}).values():
            if value and len(value) >= 4:
                text = text.replace(value, "<REDACTED>")
        return text

    def _close_stdio_log(self, name: str) -> None:
        log = self._stderr_logs.pop(name, None)
        if log is not None:
            try:
                log.close()
            except Exception:
                pass

    def _resolve_stdio_command(
        self,
        config: MCPServerConfig,
        cwd: str,
    ) -> str:
        raw = str(config.command or "").strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1].strip()

        expanded = os.path.expandvars(os.path.expanduser(raw))
        alias = Path(expanded).name.lower()
        python_aliases = {
            "python",
            "python.exe",
            "python3",
            "python3.exe",
        }

        if alias in python_aliases and Path(expanded).parent == Path("."):
            current = Path(sys.executable)
            if current.name.lower() in python_aliases and current.exists():
                return str(current.resolve())

            virtual_env = os.getenv("VIRTUAL_ENV")
            if virtual_env:
                candidate = (
                    Path(virtual_env) / "Scripts" / "python.exe"
                    if os.name == "nt"
                    else Path(virtual_env) / "bin" / "python"
                )
                if candidate.exists():
                    return str(candidate.resolve())

        path_value = Path(expanded)
        if path_value.is_absolute():
            return str(path_value)

        if any(separator in expanded for separator in ("/", "\\")):
            return str((Path(cwd) / path_value).resolve())

        located = shutil.which(expanded)
        return located or expanded

    def _resolved_stdio_args(
        self,
        command: str,
        args: tuple[str, ...],
        cwd: str,
    ) -> list[str]:
        values = list(args)
        executable = Path(command).name.lower()
        if (
            executable.startswith("python")
            and values
            and not values[0].startswith("-")
            and values[0].lower().endswith(".py")
        ):
            script = Path(
                os.path.expandvars(
                    os.path.expanduser(values[0])
                )
            )
            if not script.is_absolute():
                script = (Path(cwd) / script).resolve()
            values[0] = str(script)
        return values

    def _validate_stdio_target(
        self,
        config: MCPServerConfig,
        cwd: str,
    ) -> None:
        command = self._resolve_stdio_command(config, cwd)
        command_path = Path(command)
        if command_path.is_absolute() and not command_path.exists():
            raise MCPClientError(
                "MCP_COMMAND_NOT_FOUND",
                f"MCP command does not exist: {command}",
            )

        args = self._resolved_stdio_args(
            command,
            config.args,
            cwd,
        )
        executable = command_path.name.lower()
        if (
            executable.startswith("python")
            and args
            and not args[0].startswith("-")
            and args[0].lower().endswith(".py")
        ):
            script = Path(args[0])
            resolved = script if script.is_absolute() else Path(cwd) / script
            if not resolved.exists():
                raise MCPClientError(
                    "MCP_SCRIPT_NOT_FOUND",
                    "MCP Python script does not exist: "
                    + str(resolved.resolve()),
                )

    def _http_transport(self, config: MCPServerConfig):
        @asynccontextmanager
        async def transport() -> AsyncIterator[Any]:
            timeout = httpx2.Timeout(
                config.timeout_seconds,
                read=max(config.timeout_seconds, 300.0),
            )
            async with httpx2.AsyncClient(
                headers=dict(config.env or {}),
                timeout=timeout,
            ) as http_client:
                async with streamable_http_client(
                    str(config.url),
                    http_client=http_client,
                ) as streams:
                    yield streams
        return transport()

    def _build_client(self, config: MCPServerConfig) -> Client:
        if config.transport == "stdio":
            cwd = os.getcwd()
            command = self._resolve_stdio_command(config, cwd)
            args = self._resolved_stdio_args(
                command,
                config.args,
                cwd,
            )
            self._validate_stdio_target(config, cwd)
            stderr = tempfile.TemporaryFile(
                mode="w+",
                encoding="utf-8",
                errors="replace",
            )
            self._stderr_logs[config.name] = stderr
            parameters = StdioServerParameters(
                command=command,
                args=args,
                env=dict(config.env or {}),
                cwd=cwd,
                encoding="utf-8",
                encoding_error_handler="replace",
            )
            target = stdio_client(
                parameters,
                errlog=stderr,
            )
        else:
            target = self._http_transport(config)
        return Client(
            target,
            read_timeout_seconds=config.timeout_seconds,
        )

    async def connect(self, name: str) -> MCPServerStatus:
        if name in self._connections:
            return self._connections[name].status

        config = self._config(name)
        client: Client | None = None
        try:
            client = self._build_client(config)
            async with asyncio.timeout(config.timeout_seconds):
                await client.__aenter__()
            info = client.server_info
            status = MCPServerStatus(
                name=name,
                transport=config.transport,
                connected=True,
                effective_command=(
                    self._resolve_stdio_command(config, os.getcwd())
                    if config.transport == "stdio"
                    else None
                ),
                protocol_version=str(client.protocol_version or "") or None,
                server_name=(
                    str(getattr(info, "name", "") or "") or None
                    if info is not None
                    else None
                ),
                server_version=(
                    str(getattr(info, "version", "") or "") or None
                    if info is not None
                    else None
                ),
            )
            self._connections[name] = _Connection(
                config=config,
                client=client,
                status=status,
            )
            self._statuses[name] = status
            return status
        except Exception as exc:
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
            stderr = (
                self._stdio_error_text(config)
                if config.transport == "stdio"
                else ""
            )
            detail = str(exc).strip() or exc.__class__.__name__
            if stderr:
                detail += "\nMCP server stderr:\n" + stderr
            status = MCPServerStatus(
                name=name,
                transport=config.transport,
                connected=False,
                effective_command=(
                    self._resolve_stdio_command(config, os.getcwd())
                    if config.transport == "stdio"
                    else None
                ),
                error=detail,
            )
            self._statuses[name] = status
            self._close_stdio_log(name)
            raise MCPClientError(
                "MCP_CONNECT_FAILED",
                f"Unable to connect MCP server {name}: {detail}",
            ) from exc

    async def disconnect(self, name: str) -> None:
        connection = self._connections.pop(name, None)
        config = self._config(name)
        if connection is not None:
            try:
                await connection.client.__aexit__(None, None, None)
            finally:
                self._close_stdio_log(name)
                self._statuses[name] = MCPServerStatus(
                    name=name,
                    transport=config.transport,
                    connected=False,
                )

    async def disconnect_all(self) -> None:
        for name in list(self._connections):
            try:
                await self.disconnect(name)
            except Exception:
                connection = self._connections.pop(name, None)
                config = self._configs[name]
                self._statuses[name] = MCPServerStatus(
                    name=name,
                    transport=config.transport,
                    connected=False,
                    error=(
                        "Disconnect failed."
                        if connection is not None
                        else None
                    ),
                )

    async def reconnect(self, name: str) -> MCPServerStatus:
        if name in self._connections:
            await self.disconnect(name)
        return await self.connect(name)

    def _connection(self, name: str) -> _Connection:
        connection = self._connections.get(name)
        if not connection:
            raise MCPClientError(
                "MCP_NOT_CONNECTED",
                f"MCP server is not connected: {name}",
            )
        return connection

    async def _call(
        self,
        name: str,
        operation: str,
        callback,
    ) -> Any:
        connection = self._connection(name)
        try:
            async with asyncio.timeout(connection.config.timeout_seconds):
                return await callback(connection.client)
        except TimeoutError as exc:
            raise MCPClientError(
                "MCP_TIMEOUT",
                f"MCP {operation} timed out for server {name}.",
            ) from exc
        except MCPClientError:
            raise
        except Exception as exc:
            failed_status = MCPServerStatus(
                name=name,
                transport=connection.config.transport,
                connected=False,
                error=str(exc),
            )
            connection.status = failed_status
            self._statuses[name] = failed_status
            raise MCPClientError(
                "MCP_REQUEST_FAILED",
                f"MCP {operation} failed for server {name}: {exc}",
            ) from exc

    async def list_tools(self, name: str) -> list[MCPToolDescriptor]:
        cursor: str | None = None
        tools: list[MCPToolDescriptor] = []
        for _ in range(MAX_LIST_PAGES):
            page = await self._call(
                name,
                "tools/list",
                lambda client, cursor=cursor: client.list_tools(
                    cursor=cursor,
                    cache_mode="refresh",
                ),
            )
            for tool in page.tools:
                annotations = getattr(tool, "annotations", None)
                read_only_hint = bool(
                    getattr(annotations, "read_only_hint", False)
                    or getattr(annotations, "readOnlyHint", False)
                )
                destructive_hint = bool(
                    getattr(annotations, "destructive_hint", False)
                    or getattr(annotations, "destructiveHint", False)
                )
                tools.append(
                    MCPToolDescriptor(
                        server_name=name,
                        name=str(tool.name),
                        description=str(tool.description or ""),
                        input_schema=_tool_input_schema(tool),
                        read_only_hint=read_only_hint,
                        destructive_hint=destructive_hint,
                    )
                )
            cursor = page.next_cursor
            if cursor is None:
                return sorted(tools, key=lambda item: item.name)
        raise MCPClientError(
            "MCP_PAGE_LIMIT",
            f"MCP tools/list exceeded {MAX_LIST_PAGES} pages for {name}.",
        )

    async def list_resources(
        self,
        name: str,
    ) -> list[MCPResourceDescriptor]:
        cursor: str | None = None
        resources: list[MCPResourceDescriptor] = []
        for _ in range(MAX_LIST_PAGES):
            page = await self._call(
                name,
                "resources/list",
                lambda client, cursor=cursor: client.list_resources(
                    cursor=cursor,
                    cache_mode="refresh",
                ),
            )
            for resource in page.resources:
                resources.append(
                    MCPResourceDescriptor(
                        server_name=name,
                        uri=str(resource.uri),
                        name=str(resource.name or ""),
                        description=(
                            str(resource.description)
                            if resource.description is not None
                            else None
                        ),
                        mime_type=(
                            str(resource.mime_type)
                            if resource.mime_type is not None
                            else None
                        ),
                    )
                )
            cursor = page.next_cursor
            if cursor is None:
                return sorted(resources, key=lambda item: item.uri)
        raise MCPClientError(
            "MCP_PAGE_LIMIT",
            f"MCP resources/list exceeded {MAX_LIST_PAGES} pages for {name}.",
        )

    async def read_resource(self, name: str, uri: str) -> dict[str, Any]:
        result = await self._call(
            name,
            "resources/read",
            lambda client: client.read_resource(
                uri,
                cache_mode="refresh",
            ),
        )
        return {
            "server": name,
            "uri": uri,
            "result": _bounded_payload(
                result,
                self.max_output_chars,
            ),
        }

    async def call_tool(
        self,
        name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._call(
            name,
            "tools/call",
            lambda client: client.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=self._config(name).timeout_seconds,
            ),
        )
        return {
            "server": name,
            "tool": tool_name,
            "is_error": bool(getattr(result, "is_error", False)),
            "result": _bounded_payload(
                result,
                self.max_output_chars,
            ),
        }
