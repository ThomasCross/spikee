"""
sample_simple_chatbot.py

A ``SimpleMultiTarget`` example for the Spikee Test Chatbot.

``SimpleMultiTarget`` stores conversation history and maps each Spikee session
to one chatbot session ID. This sample sends each new message to that mapped
chatbot session.

Usage:
    spikee test --dataset datasets/example.jsonl --target sample_simple_chatbot \
        --attack <multi-turn capable attack>
"""

import json
import traceback
import uuid

import requests
from dotenv import load_dotenv

from spikee.templates.simple_multi_target import SimpleMultiTarget
from spikee.utilities.enums import ModuleTag, Turn
from spikee.utilities.hinting import (
    ModuleDescriptionHint,
    ModuleOptionsHint,
    TargetResponseHint,
)
from spikee.utilities.modules import parse_options


class SampleSimpleChatbotTarget(SimpleMultiTarget):
    def __init__(self):
        super().__init__(turn_types=[Turn.SINGLE, Turn.MULTI], backtrack=False)

    def get_description(self) -> ModuleDescriptionHint:
        return [ModuleTag.SINGLE, ModuleTag.MULTI], (
            "SimpleMultiTarget example for the Spikee Test Chatbot."
        )

    def get_available_option_values(self) -> ModuleOptionsHint:
        return ["url=http://localhost:8000", "model=gpt-4o-mini"], False

    def _new_target_session_id(self, url: str) -> str:
        session_id = str(uuid.uuid4())
        while (
            requests.get(
                f"{url.rstrip('/')}/api/sessions/{session_id}", timeout=10
            ).status_code
            == 200
        ):
            session_id = str(uuid.uuid4())
        return session_id

    def process_input(
        self,
        input_text: str,
        system_message: str | None = None,
        target_options: str | None = None,
        spikee_session_id: str | None = None,
        backtrack: bool | None = False,
    ) -> TargetResponseHint:
        options = parse_options(target_options)
        url = options.get("url", "http://localhost:8000")
        model = options.get("model", "gpt-4o-mini")

        if spikee_session_id is None:
            target_session_id = self._new_target_session_id(url)
        else:
            target_session_id = self._get_id_map(spikee_session_id)
            if target_session_id is None:
                target_session_id = self._new_target_session_id(url)
                self._update_id_map(spikee_session_id, target_session_id)

        payload = {
            "message": input_text,
            "session_id": target_session_id,
            "model": model,
        }
        if system_message:
            payload["system_prompt"] = system_message

        response = requests.post(f"{url.rstrip('/')}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        try:
            response_data = response.json()
            result = (
                response_data.get("response")
                or response_data.get("message")
                or response_data.get("content")
                or str(response_data)
            )
        except json.JSONDecodeError:
            result = response.text

        if spikee_session_id is not None:
            self._append_conversation_data(spikee_session_id, "user", input_text)
            self._append_conversation_data(spikee_session_id, "assistant", result)

        return result


if __name__ == "__main__":
    load_dotenv()
    try:
        target = SampleSimpleChatbotTarget()
        target.add_managed_dicts({})
        print(target.process_input("Hello", spikee_session_id="manual-session"))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
