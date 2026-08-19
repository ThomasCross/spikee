"""
sample_chatbot.py

A ``MultiTarget`` example for the Spikee Test Chatbot.

Unlike ``sample_simple_chatbot.py``, this sample manages its own per-session
state. The chatbot API is append-only, so backtracking creates a fresh chatbot
session and replays the remaining user messages.

Usage:
    spikee test --dataset datasets/example.jsonl --target sample_chatbot \
        --attack <multi-turn capable attack>
"""

import json
import traceback
import uuid
from typing import Any

import requests
from dotenv import load_dotenv

from spikee.templates.multi_target import MultiTarget
from spikee.utilities.enums import ModuleTag, Turn
from spikee.utilities.hinting import (
    ModuleDescriptionHint,
    ModuleOptionsHint,
    TargetResponseHint,
)
from spikee.utilities.modules import parse_options


class SampleChatbotTarget(MultiTarget):
    def __init__(self):
        super().__init__(turn_types=[Turn.SINGLE, Turn.MULTI], backtrack=True)

    def get_description(self) -> ModuleDescriptionHint:
        return [ModuleTag.SINGLE, ModuleTag.MULTI], (
            "MultiTarget example for the Spikee Test Chatbot with backtracking."
        )

    def get_available_option_values(self) -> ModuleOptionsHint:
        return ["url=http://localhost:8000", "model=gpt-4o-mini"], False

    def _new_target_session_id(self, url: str) -> str:
        # The chatbot owns its own session IDs, separate from Spikee session IDs.
        session_id = str(uuid.uuid4())
        while (
            requests.get(
                f"{url.rstrip('/')}/api/sessions/{session_id}", timeout=10
            ).status_code
            == 200
        ):
            session_id = str(uuid.uuid4())
        return session_id

    def _send_message(
        self,
        url: str,
        session_id: str,
        message: str,
        model: str,
        system_message: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "model": model,
        }
        if system_message:
            payload["system_prompt"] = system_message

        response = requests.post(f"{url.rstrip('/')}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        try:
            response_data = response.json()
            return (
                response_data.get("response")
                or response_data.get("message")
                or response_data.get("content")
                or str(response_data)
            )
        except json.JSONDecodeError:
            return response.text

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
            # Single-turn requests get an isolated chatbot conversation.
            target_session_id = self._new_target_session_id(url)
            session_data = None
        else:
            # MultiTarget gives this sample a per-Spikee-session storage slot.
            session_data = self._get_target_data(spikee_session_id)
            if session_data is None:
                session_data = {
                    "target_session_id": self._new_target_session_id(url),
                    "history": [],
                }
                self._update_target_data(spikee_session_id, session_data)
            target_session_id = session_data["target_session_id"]

        if (
            backtrack
            and spikee_session_id is not None
            and session_data is not None
            and len(session_data["history"]) >= 2
        ):
            # Remove the last user/assistant pair before rebuilding the session.
            session_data["history"] = session_data["history"][:-2]
            target_session_id = self._new_target_session_id(url)

            # Replay the retained user messages into the new append-only session.
            for message in session_data["history"]:
                if message["role"] == "user":
                    self._send_message(
                        url, target_session_id, message["content"], model, system_message
                    )

            session_data["target_session_id"] = target_session_id
            # MultiTarget state must be written back after every mutation.
            self._update_target_data(spikee_session_id, session_data)

        response = self._send_message(
            url, target_session_id, input_text, model, system_message
        )

        if spikee_session_id is not None and session_data is not None:
            # Store both sides of the turn so a later backtrack can replay it.
            session_data["history"].extend(
                [
                    {"role": "user", "content": input_text},
                    {"role": "assistant", "content": response},
                ]
            )
            self._update_target_data(spikee_session_id, session_data)

        return response


if __name__ == "__main__":
    load_dotenv()
    try:
        target = SampleChatbotTarget()
        target.add_managed_dicts({})
        print(target.process_input("Hello", spikee_session_id="manual-session"))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
