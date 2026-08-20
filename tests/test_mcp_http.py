from __future__ import annotations

import asyncio

from spikes.mcp_echo import agents_sdk_call_echo, call_echo_over_http


def test_echo_over_streamable_http() -> None:
    assert asyncio.run(call_echo_over_http("hello-loopmedic")) == "hello-loopmedic"


def test_agents_sdk_calls_echo_over_streamable_http() -> None:
    assert asyncio.run(agents_sdk_call_echo("hello-loopmedic")) == "hello-loopmedic"
