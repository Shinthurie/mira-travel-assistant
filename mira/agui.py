"""AG-UI agent wrapper with one fix for the pinned CopilotKit SDK.

``copilotkit==0.1.97`` turns the ``copilotkit_manually_emit_message`` custom event into
TEXT_MESSAGE_START/CONTENT/END events but drops them (the return values of its inner
``_dispatch_event`` calls are discarded), so only a raw CUSTOM event reaches the browser.
Mira emits its (already price-guarded) reply text that way so the text appears BEFORE the A2UI cards.

``MiraAGUIAgent`` handles exactly that one event itself and leaves everything else to CopilotKit.
If a later SDK version fixes the bug, this class can be deleted (see docs/DECISIONS.md, D22).
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from ag_ui.core import EventType, TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent
from ag_ui_langgraph import LangGraphAgent
from copilotkit import LangGraphAGUIAgent

EMIT_MESSAGE = "copilotkit_manually_emit_message"


class MiraAGUIAgent(LangGraphAGUIAgent):
    async def _handle_single_event(self, event: Any, state: Any) -> AsyncGenerator[Any, None]:
        if event.get("event") == "on_custom_event" and event.get("name") == EMIT_MESSAGE:
            data = event.get("data") or {}
            message_id, text = data.get("message_id"), data.get("message", "")
            if message_id and text:
                for ev in (
                    TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, role="assistant", message_id=message_id),
                    TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=text),
                    TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id),
                ):
                    out = LangGraphAgent._dispatch_event(self, ev)  # base dispatcher (applies its filters)
                    if out is not None:
                        yield out
            return
        async for out in super()._handle_single_event(event, state):
            yield out
