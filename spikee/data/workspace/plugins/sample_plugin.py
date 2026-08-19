"""
sample_plugin.py

This file shows a simple example plugin for Spikee.

Plugins must define a `transform(text: str, exclude_patterns: List[str] = []) -> Union[str, List[str]]` function.
Spikee will call this function for each input prompt, passing in the original text and, optionally, a list of regex
patterns that should be excluded from transformation.

Key Concepts:
- Exclusion Support: If `exclude_patterns` is provided, any substring that exactly matches one of the regex patterns
  should be preserved as-is.
- Multiple Variants: Plugins can return a single transformed string or a list of strings to test multiple variants.

Usage within Spikee:
    spikee generate --plugins sample_plugin
    spikee generate --plugins sample_plugin --plugin-options "sample_plugin:offset=5"

This sample plugin encodes text using the ROT13 cipher, with an optional offset parameter to shift the encoding.
"""

from spikee.templates.plugin import Plugin
from spikee.utilities.hinting import ModuleDescriptionHint, ModuleOptionsHint
from spikee.utilities.modules import parse_options


class SamplePlugin(Plugin):
    def get_description(self) -> ModuleDescriptionHint:
        return [], "Encode text with ROT13."

    def get_available_option_values(self) -> ModuleOptionsHint:
        return ["offset=13", "offset=<integer>"], False

    def transform(
        self,
        content: str,
        exclude_patterns: list[str] | None = None,
        plugin_option: str = "",
    ) -> str | list[str]:
        # Spikee passes this plugin's portion of --plugin-options as a string.
        offset_text = parse_options(plugin_option).get("offset", "13")
        try:
            offset = int(offset_text)
        except ValueError as error:
            raise ValueError("offset must be an integer") from error

        # Direct Plugin subclasses choose how to use exclude_patterns. This
        # example intentionally encodes the whole prompt, including exclusions.
        encoded_characters = []
        for character in content:
            if "a" <= character <= "z":
                encoded_characters.append(
                    chr((ord(character) - ord("a") + offset) % 26 + ord("a"))
                )
            elif "A" <= character <= "Z":
                encoded_characters.append(
                    chr((ord(character) - ord("A") + offset) % 26 + ord("A"))
                )
            else:
                encoded_characters.append(character)

        # Return one transformed prompt. Return a list[str] to create variants.
        return "".join(encoded_characters)

if __name__ == "__main__":
    # This allows the plugin to be run directly for testing.
    plugin = SamplePlugin()
    test_text = "Hello, World!"
    transformed_text = plugin.transform(test_text)
    print(f"Original: {test_text}")
    print(f"Transformed: {transformed_text}")