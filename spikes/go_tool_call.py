from __future__ import annotations

import asyncio

from agents import Agent, Runner, function_tool

from loopmedic.runner.config import build_model, model_name


@function_tool(failure_error_function=None)
def echo(text: str) -> str:
    """Return the given text unchanged."""
    return text


async def run_spike() -> str:
    agent = Agent(
        name="GoEcho",
        instructions=(
            "Call the echo tool with text hello-loopmedic, then report "
            "the tool's return value exactly."
        ),
        model=build_model(),
        tools=[echo],
    )
    result = await Runner.run(
        agent,
        "Call echo with text hello-loopmedic.",
    )
    return str(result.final_output)


def main() -> None:
    print(f"model={model_name()}")
    output = asyncio.run(run_spike())
    print(output)
    if "hello-loopmedic" not in output:
        raise SystemExit("echo tool result not found in model output")


if __name__ == "__main__":
    main()
