from abc import ABC, abstractmethod

from spikee.templates.module import Module
from spikee.utilities.enums import Turn
from spikee.utilities.hinting import Content, TargetResponseHint


class Target(Module, ABC):
    def __init__(self, turn_types: list[Turn] | None = None, backtrack: bool = False):
        super().__init__()

        turn_types = [Turn.SINGLE] if turn_types is None else turn_types

        self.config = {
            "single-turn": Turn.SINGLE in turn_types,
            "multi-turn": Turn.MULTI in turn_types,
            "backtrack": backtrack,
        }

    @abstractmethod
    def process_input(
        self,
        input_text: Content,
        system_message: Content | None = None,
        target_options: str | None = None,
    ) -> TargetResponseHint:
        """Sends prompts to the defined target

        Args:
            input_text (Content): User Prompt
            system_message (Optional[Content], optional): System Prompt. Defaults to None.
            target_options (Optional[str], optional): Target options. Defaults to None.

        Returns:
            Content: Response from the target
            bool: Whether the target's response indicates a successful attack (if applicable)
            Tuple[Union[Content, bool], Any]: Optionally return additional metadata along with the response and success status
            throws tester.GuardrailTrigger: Indicates guardrail was triggered
            throws Exception: Raises exception on failure
        """
