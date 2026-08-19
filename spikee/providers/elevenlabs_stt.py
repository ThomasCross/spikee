"""
ElevenLabs Speech-to-Text provider module for Spikee.

Input: base64-encoded audio in HumanMessage content.
Output: transcribed text in AIMessage content.

Additional Args: none currently exposed.
"""

import base64
import os
from io import BytesIO
from typing import ClassVar

from spikee.templates.provider import Provider
from spikee.utilities.enums import ModuleTag
from spikee.utilities.hinting import Audio, ModuleDescriptionHint
from spikee.utilities.llm_message import (
    AIMessage,
    HumanMessage,
    MessageHint,
    single_message,
)


class ElevenLabsSTTProvider(Provider):
    """ElevenLabs Speech-to-Text (Scribe) provider"""

    _MIME_MAP: ClassVar[dict[str, str]] = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
    }

    @property
    def default_model(self) -> str:
        return "scribe_v1"

    @property
    def models(self) -> dict[str, str]:
        return {
            "scribe_v1": "scribe_v1",
            "scribe_v2": "scribe_v2",
        }

    @property
    def audio_formats(self) -> set[str]:
        return {"mp3", "wav", "ogg", "flac"}

    def setup(
        self,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **additional_kwargs,
    ) -> None:
        self.model = model

        try:
            from elevenlabs import ElevenLabs

            self.client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        except ImportError:
            raise ImportError(
                "[Import Error] Provider Module 'elevenlabs_stt' is missing required packages. "
                "Please run `pip install elevenlabs` to install them."
            )

    def get_description(self) -> ModuleDescriptionHint:
        return [
            ModuleTag.AUDIO,
            ModuleTag.LLM_STT,
        ], "STT Provider for ElevenLabs Scribe speech-to-text models."

    def _invoke(self, messages: MessageHint) -> AIMessage:
        """Invoke ElevenLabs Scribe STT with base64-encoded audio. Returns transcribed text."""

        msg, _ = single_message(messages)

        content = msg.content

        if not isinstance(content, Audio):
            raise TypeError(
                "ElevenLabs STT Provider requires a user message containing base64-encoded audio."
            )

        audio_bytes = content.get_raw_audio()
        audio_format = content.format
        if audio_format not in self.audio_formats:
            content.convert_audio_format(target_format="mp3")
            audio_bytes = content.get_raw_audio()
            audio_format = "mp3"

        mime = self._MIME_MAP.get(audio_format, "audio/mpeg")
        audio_buffer = BytesIO(audio_bytes)

        response = self.client.speech_to_text.convert(
            model_id=self.model,
            file=(f"audio.{audio_format}", audio_buffer, mime),
        )

        return AIMessage(content=response.text)


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    pcm_path = sys.argv[1] if len(sys.argv) > 1 else "audio_file.pcm"
    with open(pcm_path, "rb") as f:
        raw = f.read()
    audio = Audio(base64.b64encode(raw).decode(), audio_format="pcm")
    provider = ElevenLabsSTTProvider()
    provider.setup(model="scribe_v1")
    response = provider.invoke([HumanMessage(content=audio)])
    print(response.content)
