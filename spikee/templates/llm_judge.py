from .judge import Judge
from spikee.utilities.llm import get_llm, SUPPORTED_LLM_MODELS


class LLMJudge(Judge):
    DEFAULT_LLM_MODEL = "openai-gpt-4.1-mini"

    def get_available_option_values(self):
        """
        Returns the list of supported judge_options; first option is default.
        """
        options = [self.DEFAULT_LLM_MODEL]  # Default first
        options.extend([model for model in SUPPORTED_LLM_MODELS if model != self.DEFAULT_LLM_MODEL])
        return options

    def _get_llm(self, judge_options):
        """
        Initialize and return the appropriate LLM based on judge_options.
        """
        try:
            llm = get_llm(judge_options)
            return llm
        except ValueError as e:
            print(f"[Error] {e}")
            return None
