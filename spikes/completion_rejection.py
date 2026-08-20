from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    Model,
    ModelResponse,
    OutputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    output_guardrail,
)
from agents.items import TResponseInputItem, TResponseStreamEvent
from agents.model_settings import ModelSettings
from agents.models.interface import ModelTracing
from agents.usage import Usage
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_prompt_param import ResponsePromptParam

TASK_COMPLETE = "TASK COMPLETE"
CONTINUED = "CONTINUED"


@output_guardrail
async def reject_task_complete(
    ctx: RunContextWrapper[Any],
    agent: Agent[Any],
    output: object,
) -> GuardrailFunctionOutput:
    text = output if isinstance(output, str) else str(output)
    tripped = text.strip() == TASK_COMPLETE
    return GuardrailFunctionOutput(
        output_info={"output": text, "rejected": tripped},
        tripwire_triggered=tripped,
    )


def _as_input_list(value: str | list[Any]) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return [{"role": "user", "content": value}]


def history_from_tripwire(exc: OutputGuardrailTripwireTriggered) -> list[Any]:
    data = exc.run_data
    if data is None:
        raise RuntimeError("OutputGuardrailTripwireTriggered has no run_data")
    history = _as_input_list(data.input)
    for item in data.new_items:
        history.append(item.to_input_item())
    return history


def _contains_continue(value: str | list[TResponseInputItem]) -> bool:
    if isinstance(value, str):
        return "CONTINUE" in value
    return any("CONTINUE" in str(item) for item in value)


class ScriptedModel(Model):
    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        text = CONTINUED if _contains_continue(input) else TASK_COMPLETE
        message = ResponseOutputMessage(
            id="msg_scripted",
            content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
            role="assistant",
            status="completed",
            type="message",
        )
        return ModelResponse(output=[message], usage=Usage(), response_id=None)

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("Spike A uses Runner.run, not streaming")
        yield  # pragma: no cover


AGENT = Agent(
    name="ToyCompleter",
    model=ScriptedModel(),
    instructions=(
        "You may output only one of two strings. "
        f"If the latest user message contains the token CONTINUE, reply with exactly {CONTINUED}. "
        f"Otherwise reply with exactly {TASK_COMPLETE}."
    ),
    output_guardrails=[reject_task_complete],
)


async def run_spike() -> tuple[str, str]:
    first_input = "Finish the task."
    try:
        await Runner.run(AGENT, first_input)
        raise RuntimeError("guardrail did not trip")
    except OutputGuardrailTripwireTriggered as exc:
        history = history_from_tripwire(exc)
        history.append(
            {
                "role": "user",
                "content": (
                    "CONTINUE. Previous completion was rejected because "
                    "required invariants are unmet."
                ),
            }
        )
        continued = await Runner.run(AGENT, history)
        first_rejected = str(exc.guardrail_result.output.output_info["output"])
        return first_rejected, str(continued.final_output)


def main() -> None:
    rejected, continued = asyncio.run(run_spike())
    print(f"rejected={rejected!r}")
    print(f"continued={continued!r}")
    if continued.strip() == rejected.strip():
        raise SystemExit("continued output matched rejected output")


if __name__ == "__main__":
    main()
