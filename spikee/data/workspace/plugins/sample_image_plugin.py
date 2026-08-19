"""
sample_image_plugin.py

This file demonstrates a simple image plugin for Spikee.

Image plugins receive an ``Image`` object containing Base64-encoded image data
and return an ``Image`` object. This example adds a visible red border, making
it easy to confirm that the plugin changed the image.

Usage within Spikee:
    spikee generate --plugins text2image~sample_image_plugin

Requires Pillow. Install it with:
    pip install Pillow
"""

import base64
import binascii
from io import BytesIO

try:
    from PIL import Image as PillowImage
    from PIL import ImageOps
except ImportError as error:
    raise ImportError(
        "sample_image_plugin requires Pillow. Install it with: pip install Pillow"
    ) from error

from spikee.templates.plugin import Plugin
from spikee.utilities.enums import ModuleTag
from spikee.utilities.hinting import Image
from spikee.utilities.hinting import ModuleDescriptionHint, ModuleOptionsHint


class SampleImagePlugin(Plugin):
    def get_description(self) -> ModuleDescriptionHint:
        return [ModuleTag.IMAGE, ModuleTag.FORMATTING], (
            "Adds a red border to an image. (Requires: `pip install Pillow`)"
        )

    def get_available_option_values(self) -> ModuleOptionsHint:
        return [], False

    def transform(
        self,
        content: Image,
        exclude_patterns: list[str] | None = None,
        plugin_option: str = "",
    ) -> Image:
        try:
            # Spikee stores the image payload as a Base64 string on Image.content.
            image_bytes = base64.b64decode(content.content)
            image = PillowImage.open(BytesIO(image_bytes))
            # Load now so invalid image data is reported before transformation.
            image.load()
        except (ValueError, binascii.Error, OSError) as error:
            raise ValueError("content must contain a valid Base64-encoded image") from error

        # Apply the image transformation with Pillow.
        bordered_image = ImageOps.expand(image, border=10, fill="red")
        output = BytesIO()
        bordered_image.save(output, format="PNG")

        # Return a new Spikee Image wrapper containing the Base64 PNG data.
        output_data = base64.b64encode(output.getvalue()).decode("utf-8")
        return Image(output_data)

if __name__ == "__main__":
    # This allows the plugin to be run directly for testing.
    plugin = SampleImagePlugin()
    
    # Create a simple 100x100 white image for testing.
    test_image = PillowImage.new("RGB", (100, 100), color="white")
    buffer = BytesIO()
    test_image.save(buffer, format="PNG")
    test_image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    spikee_image = Image(test_image_base64)

    transformed_image = plugin.transform(spikee_image)
    print(f"Transformed image Base64: {transformed_image.content[:50]}...")  # Print first 50 chars