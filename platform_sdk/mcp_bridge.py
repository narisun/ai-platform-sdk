"""
MCPToolBridge — connects to an MCP server over SSE and converts every
registered tool into a LangChain StructuredTool with a dynamically
generated Pydantic schema.

Key improvements over the original:
- Reads each tool's inputSchema and builds a proper Pydantic args model
  instead of assuming (query, session_id) for every tool.
- Uses a factory function to capture the closure variable correctly.
- Structured logging throughout.

Session-ID injection
────────────────────
execute_read_query requires a session_id (UUID) for workspace schema scoping
and OPA policy enforcement.  The LLM should never choose this value — it must
come from the server's trusted session context.

Two complementary mechanisms provide it:

1. Per-bridge injection (Chainlit path):
   Pass session_id= to MCPToolBridge.__init__().  The value is captured in
   every invoke closure built by get_langchain_tools(), so the LLM's
   session_id argument is silently overridden on every call.

2. Context-variable injection (REST API path / fallback):
   Call set_session_id(uuid) before invoking the agent and reset it afterward.
   asyncio inherits ContextVars into child tasks, so the value is visible to
   tool invocations even when the bridge is shared across requests.

Connection lifecycle note
─────────────────────────
The MCP sse_client() uses anyio.create_task_group() internally, which
creates a cancel scope that is *owned by the calling task*.  Chainlit
runs on_chat_start and on_chat_end in different asyncio tasks, so if the
AsyncExitStack were managed directly in those callbacks the scope-exit
would happen in a different task than the scope-entry — AnyIO raises:

    "Attempted to exit cancel scope in a different task than it was
    entered in"

Fix: the entire AsyncExitStack (and everything it enters) lives inside a
dedicated background asyncio.Task (_connection_task).  That task is the
sole owner of all cancel scopes.  connect() and disconnect() communicate
with it only through asyncio.Event objects, which are cross-task-safe.
"""
import asyncio
import contextvars
from typing import Any, Optional

# ---- Session-ID context variable --------------------------------------------
# Holds the trusted session UUID for the current async task tree.
# asyncio copies ContextVars into child tasks, so a value set before
# agent.ainvoke() is visible inside every tool invocation that runs beneath it.
_session_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mcp_session_id", default=None
)


def set_session_id(session_id: str) -> "contextvars.Token[Optional[str]]":
    """
    Bind a trusted session UUID to the current async context.

    Call this before invoking the agent; always reset with the returned token:

        token = set_session_id(body.session_id)
        try:
            result = await agent_executor.ainvoke(...)
        finally:
            reset_session_id(token)
    """
    return _session_id_ctx.set(session_id)


def reset_session_id(token: "contextvars.Token[Optional[str]]") -> None:
    """Restore the previous session_id binding after an agent invocation."""
    _session_id_ctx.reset(token)

from langchain_core.tools import StructuredTool
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from platform_sdk import get_logger
from pydantic import Field, create_model  # L2: import at module level, not inside loop

# Use structlog logger (supports keyword args) rather than standard logging.getLogger()
log = get_logger(__name__)

# Maps JSON Schema primitive types to Python types
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _build_args_model(tool_name: str, input_schema: dict) -> type:
    """
    Dynamically create a Pydantic BaseModel from a JSON Schema object.

    This makes the MCP bridge truly generic — it works with any tool
    regardless of its parameter names or types.
    """
    fields: dict[str, Any] = {}
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    for field_name, field_schema in properties.items():
        python_type = _JSON_TYPE_MAP.get(field_schema.get("type", "string"), str)
        description = field_schema.get("description", "")
        if field_name in required_fields:
            fields[field_name] = (python_type, Field(..., description=description))
        else:
            default = field_schema.get("default")
            fields[field_name] = (Optional[python_type], Field(default=default, description=description))

    model_name = "".join(word.title() for word in tool_name.split("_")) + "Args"
    return create_model(model_name, **fields)


def _make_invoke_fn(
    session: ClientSession,
    tool_name: str,
    input_schema: dict,
    bridge_session_id: Optional[str] = None,
):
    """
    Factory that returns an async callable bound to a specific tool name.

    Using a factory avoids the classic loop-closure bug where all tools
    end up calling the last tool in the list.

    For any tool that declares a `session_id` parameter in its JSON Schema,
    the session_id argument is overridden with the trusted value from the
    bridge (per-session injection) or the ContextVar (shared-bridge / REST API
    injection).  The LLM's own session_id value is discarded — it should never
    control which workspace schema is queried.

    Detection is schema-based rather than name-based so this bridge works for
    any tool that requires session scoping, not just execute_read_query.
    """
    _is_session_scoped = "session_id" in input_schema.get("properties", {})

    async def invoke(**kwargs: Any) -> str:
        try:
            # Inject trusted session_id, overriding whatever the LLM supplied.
            # Priority: per-bridge value > ContextVar > LLM-supplied (kept as last resort).
            if _is_session_scoped:
                trusted_id = bridge_session_id or _session_id_ctx.get()
                if trusted_id:
                    kwargs["session_id"] = trusted_id
                    log.debug("session_id_injected", tool=tool_name, source="bridge" if bridge_session_id else "ctx")
                else:
                    # No trusted ID available — the OPA _valid_session_id rule will
                    # reject this call, which is the correct secure behaviour.
                    log.warning("session_id_not_injected", tool=tool_name,
                                reason="no bridge_session_id and no ContextVar set")

            log.debug("mcp_tool_call", tool=tool_name, args=list(kwargs.keys()))
            result = await session.call_tool(tool_name, arguments=kwargs)
            if result.content:
                return result.content[0].text
            return "Tool returned no content."
        except Exception as exc:
            log.error("mcp_tool_error", tool=tool_name, error=str(exc))
            # L6: returning an error string (rather than re-raising) keeps LangGraph's
            # tool-call loop alive so the agent can reason about the failure.
            # If this causes undesired reasoning on error content, consider raising
            # ToolException instead to let LangGraph handle it as a hard stop.
            return f"Tool execution error: {exc}"

    invoke.__name__ = tool_name
    return invoke


class MCPToolBridge:
    """Manages the SSE connection lifecycle to one MCP server.

    The SSE connection (and all AnyIO cancel scopes it creates) is owned by
    a single background asyncio Task.  connect() and disconnect() signal that
    task via Events so they are safe to call from any other task — which is
    required for Chainlit, where on_chat_start and on_chat_end run in
    different asyncio tasks.
    """

    def __init__(
        self,
        sse_url: str,
        agent_context: Any | None = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            sse_url:       Full SSE URL, e.g. http://salesforce-mcp:8081/sse
            agent_context: Optional AgentContext from a verified JWT.  When set,
                           serialized as base64-JSON in the X-Agent-Context header
                           on the SSE connection and every MCP tool call POST.
                           MCP servers extract this header to enforce row-level
                           and column-level security before querying the database.
            session_id:    Trusted session UUID for this bridge instance.
                           When set, all execute_read_query calls will use this
                           value as session_id, overriding whatever the LLM passes.
                           Use this for per-session bridges (e.g. Chainlit).
                           For shared bridges (e.g. REST API) use set_session_id()
                           ContextVar injection instead.
        """
        self.sse_url = sse_url
        self._agent_context = agent_context
        self._session_id = session_id
        self._session: Optional[ClientSession] = None
        # Lifecycle primitives — initialised in connect()
        self._stop_event: Optional[asyncio.Event] = None
        self._connected_event: Optional[asyncio.Event] = None
        self._connect_error: Optional[BaseException] = None
        self._bg_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def _build_auth_headers(self) -> dict[str, str]:
        """Return HTTP headers carrying the agent context for this session."""
        if self._agent_context is None:
            return {}
        try:
            return {"X-Agent-Context": self._agent_context.to_header_value()}
        except Exception:
            log.warning("failed_to_encode_agent_context")
            return {}

    async def connect(
        self,
        max_retries: int = 8,
        retry_delay: float = 3.0,
    ) -> "MCPToolBridge":
        """Establish the SSE connection and MCP handshake.

        Spawns a background task that owns the AsyncExitStack (and all the
        AnyIO cancel scopes inside it) for the lifetime of the connection.
        Returns once the MCP handshake is complete.

        Retries on connection-refused / network errors (common during stack
        startup when docker depends_on healthy checks pass a moment before
        the SSE endpoint is fully serving).

        Args:
            max_retries:  Maximum connection attempts before giving up.
            retry_delay:  Seconds to wait between attempts.
        """
        from contextlib import AsyncExitStack

        auth_headers = self._build_auth_headers()

        last_exc: Optional[BaseException] = None

        for attempt in range(1, max_retries + 1):
            self._stop_event = asyncio.Event()
            self._connected_event = asyncio.Event()
            self._connect_error = None

            async def _connection_task() -> None:
                """Background task: owns the SSE + MCP context managers."""
                try:
                    async with AsyncExitStack() as stack:
                        streams = await stack.enter_async_context(
                            sse_client(self.sse_url, headers=auth_headers or None)
                        )
                        self._session = await stack.enter_async_context(
                            ClientSession(streams[0], streams[1])
                        )
                        await self._session.initialize()
                        log.info(
                            "mcp_connected",
                            url=self.sse_url,
                            with_auth=bool(auth_headers),
                        )
                        # Signal connect() that we are ready
                        self._connected_event.set()
                        # Hold the connection open until disconnect() is called
                        await self._stop_event.wait()
                except BaseException as exc:
                    self._connect_error = exc
                    # Unblock connect() even on failure so it can propagate
                    self._connected_event.set()
                finally:
                    self._session = None

            # Use get_running_loop() instead of deprecated get_event_loop()
            # (Python 3.12+).  Also capture OTel context for the background task
            # so spans are correctly parented.
            try:
                import opentelemetry.context as _otel_ctx
                _ctx = _otel_ctx.get_current()
            except ImportError:
                _ctx = None

            loop = asyncio.get_running_loop()
            if _ctx is not None:
                import contextvars
                ctx = contextvars.copy_context()
                self._bg_task = loop.create_task(_connection_task(), context=ctx)
            else:
                self._bg_task = loop.create_task(_connection_task())

            # Wait for the handshake (or an error) before returning
            await self._connected_event.wait()

            if self._connect_error is None:
                return self  # success

            last_exc = self._connect_error
            # Cancel the failed background task before retrying
            if self._bg_task and not self._bg_task.done():
                self._bg_task.cancel()
                try:
                    await self._bg_task
                except Exception:
                    pass

            if attempt < max_retries:
                log.warning(
                    "mcp_connect_retry",
                    url=self.sse_url,
                    attempt=attempt,
                    max=max_retries,
                    error=str(last_exc),
                )
                await asyncio.sleep(retry_delay)

        raise last_exc from last_exc  # type: ignore[misc]

    async def disconnect(self) -> None:
        """Signal the background task to exit and wait for it to finish.

        Safe to call from any task — this only touches asyncio primitives,
        never AnyIO cancel scopes directly.
        """
        if self._stop_event:
            self._stop_event.set()
        if self._bg_task and not self._bg_task.done():
            try:
                await self._bg_task
            except Exception:
                pass  # already logged inside _connection_task
        self._bg_task = None
        log.info("mcp_disconnected", url=self.sse_url)

    async def get_langchain_tools(self) -> list[StructuredTool]:
        """
        Fetch all tools from the MCP server and return them as LangChain tools.

        Each tool's JSON Schema is used to build a typed Pydantic model,
        so LangGraph can validate arguments before dispatching.
        """
        if not self._session:
            raise RuntimeError("Call connect() before get_langchain_tools()")

        mcp_tools = await self._session.list_tools()
        langchain_tools: list[StructuredTool] = []

        for tool in mcp_tools.tools:
            input_schema = getattr(tool, "inputSchema", None) or {}
            invoke_fn = _make_invoke_fn(
                self._session, tool.name, input_schema, bridge_session_id=self._session_id
            )

            kwargs: dict[str, Any] = dict(
                coroutine=invoke_fn,
                name=tool.name,
                description=tool.description or f"Executes the {tool.name} tool.",
            )
            if input_schema.get("properties"):
                kwargs["args_schema"] = _build_args_model(tool.name, input_schema)

            langchain_tools.append(StructuredTool.from_function(**kwargs))
            log.debug("mcp_tool_registered", tool=tool.name)

        log.info("mcp_tools_loaded", count=len(langchain_tools))
        return langchain_tools
