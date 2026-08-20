from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer

echo_server = MCPServer("echo")


@echo_server.tool()
def echo(text: str) -> str:
    """Return the given text unchanged."""
    return text


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def echo_http() -> AsyncIterator[str]:
    port = _free_port()
    app = echo_server.streamable_http_app(host="127.0.0.1")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = False
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                raise RuntimeError(f"uvicorn exited before start: {task.exception()}")
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await task


def _tool_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not content:
        return str(result)
    first = content[0]
    return str(getattr(first, "text", first))


async def call_echo_over_http(text: str) -> str:
    async with echo_http() as url:
        async with Client(url) as client:
            result = await client.call_tool("echo", {"text": text})
            return _tool_text(result)


async def agents_sdk_call_echo(text: str) -> str:
    async with echo_http() as url:
        async with MCPServerStreamableHttp(
            name="echo",
            params={"url": url},
        ) as mcp_client:
            tools = await mcp_client.list_tools()
            if not any(tool.name == "echo" for tool in tools):
                names = [tool.name for tool in tools]
                raise RuntimeError(f"echo tool missing: {names}")
            result = await mcp_client.call_tool("echo", {"text": text})
            return _tool_text(result)


async def run_spike() -> str:
    async with echo_http() as url:
        async with MCPServerStreamableHttp(
            name="echo",
            params={"url": url},
        ) as mcp_client:
            agent = Agent(
                name="EchoCaller",
                instructions=(
                    "Use the echo tool. Call it with text hello-loopmedic "
                    "and then report the tool's return value exactly."
                ),
                mcp_servers=[mcp_client],
            )
            result = await Runner.run(
                agent,
                "Call echo with text hello-loopmedic.",
            )
            return str(result.final_output)


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for this spike")
    output = asyncio.run(run_spike())
    print(output)
    if "hello-loopmedic" not in output:
        raise SystemExit("echo tool result not found in agent output")


if __name__ == "__main__":
    main()
