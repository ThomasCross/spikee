from abc import ABC, abstractmethod
from typing import overload

from spikee.templates.module import Module
from spikee.utilities.hinting import Content


class Plugin(Module, ABC):
    @abstractmethod
    @overload
    def transform(
        self,
        content: Content,
        exclude_patterns: list[str] | None = None,
        plugin_option: str = "",
    ) -> Content | list[Content]:
        pass

    @abstractmethod
    @overload
    def transform(
        self,
        text: str,
        exclude_patterns: list[str] | None = None,
        plugin_option: str = "",
    ) -> str | list[str]:
        pass
