"""
sample_basic_plugin.py

This file demonstrates a simple BasicPlugin example for Spikee.

BasicPlugin plugins define a `plugin_transform(text: str, plugin_option: str = "") -> str` method.
Spikee handles the surrounding `transform()` call and sends each editable part of the input to `plugin_transform()`.

Key Concepts:
- Exclusion Support: Text matching an exclusion pattern is preserved automatically.
- Simple Transformations: Write only the transformation for editable text in `plugin_transform()`.

Usage within Spikee:

    spikee generate --plugins sample_basic_plugin

This sample plugin transforms editable text to uppercase.
"""

from spikee.templates.basic_plugin import BasicPlugin
from spikee.utilities.hinting import ModuleDescriptionHint, ModuleOptionsHint


class SampleBasicPlugin(BasicPlugin):
    """Uppercase editable text while preserving excluded text."""

    def get_description(self) -> ModuleDescriptionHint:
        return [], "Uppercase text while preserving excluded patterns."

    def get_available_option_values(self) -> ModuleOptionsHint:
        return [], False

    def plugin_transform(self, text: str, plugin_option: str = "") -> str:
        return text.upper()


if __name__ == "__main__":
    # This allows the plugin to be run directly for testing.
    plugin = SampleBasicPlugin()
    test_text = "Hello, World!"
    transformed_text = plugin.plugin_transform(test_text)
    print(f"Original: {test_text}")
    print(f"Transformed: {transformed_text}")