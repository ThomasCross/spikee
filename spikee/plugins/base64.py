"""
Base64 Encoding Plugin

This plugin transforms the input text into Base64 encoding.

Usage:
    spikee generate --plugins base64

Parameters:
    text (str): The input text to be transformed.

Returns:
    str: The transformed text in Base64 encoding.
"""

import base64

from spikee.templates.plugin import Plugin
from spikee.utilities.enums import ModuleTag
from spikee.utilities.hinting import ModuleDescriptionHint, ModuleOptionsHint


class Base64(Plugin):
    def get_description(self) -> ModuleDescriptionHint:
        return [ModuleTag.ENCODING], "Transforms text into Base64 encoding."

    def get_available_option_values(self) -> ModuleOptionsHint:
        """Return supported attack options; Tuple[options (default is first), llm_required]"""
        return [], False

    def transform(self, content: str, exclude_patterns: list[str] | None = None) -> str:
        """
        Transforms the input text into Base64 encoding.

        Args:
            content (str): The input text.

        Returns:
            str: The transformed text in Base64 encoding.
        """
        return base64.b64encode(content.encode()).decode()
