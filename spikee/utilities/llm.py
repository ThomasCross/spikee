from typing import Dict, List
import os
import json

# region Models + Prefixes
EXAMPLE_LLM_MODELS = [
    "openai-gpt-4.1-mini",
    "openai-gpt-4o",
    "offline",
]

SUPPORTED_LLM_MODELS = [
    "llamaccp-server",
    "offline",
    "mock",
]

SUPPORTED_PREFIXES = [
    "openai-",
    "google-",
    "bedrock-",     # BedrockChat for Anthropic Models
    "bedrockcv-",   # BedrockChatConverse for other model compatibility
    "ollama-",
    "llamaccp-server-",
    "together-",
    "mock-",
]


def get_example_llm_models() -> List[str]:
    """Return the list of example LLM models."""
    return EXAMPLE_LLM_MODELS


def get_supported_llm_models() -> List[str]:
    """Return the list of supported LLM models."""
    return SUPPORTED_LLM_MODELS


def get_supported_prefixes() -> List[str]:
    """Return the list of supported LLM model prefixes."""
    return SUPPORTED_PREFIXES
# endregion

# region TogetherAI


# Map of shorthand keys to TogetherAI model identifiers
TOGETHER_AI_MODEL_MAP: Dict[str, str] = {
    "gemma2-8b": "google/gemma-2-9b-it",
    "gemma2-27b": "google/gemma-2-27b-it",
    "llama4-maverick-fp8": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "llama4-scout": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "llama31-8b": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "llama31-70b": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    "llama31-405b": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    "llama33-70b": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "mixtral-8x7b": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "mixtral-8x22b": "mistralai/Mixtral-8x22B-Instruct-v0.1",
    "qwen3-235b-fp8": "Qwen/Qwen3-235B-A22B-fp8-tput",
}

# Default shorthand key
DEFAULT_TOGETHER_AI_KEY = "llama31-8b"


def _resolve_togetherai_model(key: str) -> str:
    """
    Convert a shorthand key to the full model identifier.
    Raises ValueError for unknown keys.
    """
    if key not in TOGETHER_AI_MODEL_MAP:
        valid = ", ".join(TOGETHER_AI_MODEL_MAP.keys())
        raise ValueError(f"Unknown model key '{key}'. Valid keys: {valid}")
    return TOGETHER_AI_MODEL_MAP[key]
# endregion


class LLMWrapper():
    """
    A wrapper class for LLM instances that provides a consistent interface and can be extended with additional functionality.
    """

    def __init__(self, model_name, llm_instance):
        self.model_name = model_name
        self.llm = llm_instance

        # Set up billing tracking
        self.__billing_path = os.path.join(os.getcwd(), "billing.json")
        self.__billing = self.__read_billing()

        if self.__billing is not None and self.model_name in self.__billing['models']:
            self.__input_costs = self.__billing['models'][self.model_name].get('input_cost', 0)
            self.__output_costs = self.__billing['models'][self.model_name].get('output_cost', 0)
        else:
            self.__billing = None

    def invoke(self, messages):
        if self.llm is None:
            raise ValueError("LLM instance is not initialized.")

        response = self.llm.invoke(messages)

        # Update billing information if available
        if self.__billing is not None:
            if self.model_name.startswith("bedrock-"):
                usage = response.additional_kwargs.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

            elif self.model_name.startswith("bedrockcv-"):
                input_tokens = response.usage_metadata.get("input_tokens", 0)
                output_tokens = response.usage_metadata.get("output_tokens", 0)

            elif self.model_name.startswith("google-"):
                input_tokens = response.usage_metadata.get("input_tokens", 0)
                output_tokens = response.usage_metadata.get("output_tokens", 0)

            elif self.model_name.startswith("openai-"):
                usage = response.response_metadata.get("token_usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

            else:
                return response

            self.__update_billing(input_tokens, output_tokens)

        return response

    def __read_billing(self):
        """Used to initially read billing costs."""
        if not os.path.exists(self.__billing_path):
            return None

        with open(self.__billing_path, "r", encoding="utf-8") as f:
            billing_data = json.load(f)

        return billing_data

    def __update_billing(self, input_tokens, output_tokens):
        """Used to update billing costs after each LLM invocation."""
        with open(self.__billing_path, "r+", encoding="utf-8") as f:
            self.__billing = json.load(f)

            input_cost = input_tokens * self.__input_costs
            output_cost = output_tokens * self.__output_costs
            cost = (input_cost + output_cost) / 1000000

            print(f"Cost: ${cost:.8f}, Input: {input_tokens}, Output: {output_tokens}")

            self.__billing['models'][self.model_name]['input_tokens'] = (
                self.__billing['models'][self.model_name].get('input_tokens', 0) + input_tokens
            )
            self.__billing['models'][self.model_name]['output_tokens'] = (
                self.__billing['models'][self.model_name].get('output_tokens', 0) + output_tokens
            )

            self.__billing['total_cost'] = cost + self.__billing.get('total_cost', 0)

            f.seek(0)
            f.truncate()
            f.write(json.dumps(self.__billing, indent=2))


def validate_llm_option(option: str) -> bool:
    """
    Validate if the provided options correspond to a supported LLM model.
    """
    if option is None:
        raise ValueError(
            "LLM option cannot be None, ensure than modules leveraging LLM utilities specify an LLM option."
        )

    return option in SUPPORTED_LLM_MODELS or any(
        option.startswith(prefix) for prefix in SUPPORTED_PREFIXES
    )


def get_llm(options=None, max_tokens=8, temperature=0) -> LLMWrapper:
    """
    Initialize and return the appropriate LLM based on options.

    Arguments:
        options (str): The LLM model option string.
        max_tokens (int): Maximum tokens for the LLM response (Default: 8 for LLM Judging).
        temperature (float): Sampling temperature for the LLM (Default: 0).
    """
    if not validate_llm_option(options):
        raise ValueError(
            f"Unsupported LLM option: '{options}'. "
            f"Supported Prefixes: {SUPPORTED_PREFIXES}, Supported Models: {SUPPORTED_LLM_MODELS}"
        )

    if options.startswith("openai-"):
        from langchain_openai import ChatOpenAI

        model_name = options.replace("openai-", "")
        return LLMWrapper(
            options,
            ChatOpenAI(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=None,
                max_retries=2,
            )
        )

    elif options.startswith("google-"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = options.replace("google-", "")
        return LLMWrapper(
            options,
            ChatGoogleGenerativeAI(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=None,
                max_retries=2,
            )
        )

    elif options.startswith("bedrock-"):
        from langchain_aws import ChatBedrock

        model_name = options.replace("bedrock-", "")
        return LLMWrapper(
            options,
            ChatBedrock(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature
            )
        )

    elif options.startswith("bedrockcv-"):
        from langchain_aws import ChatBedrockConverse

        if max_tokens is None:
            max_tokens = 8192  # Set a high default if None is provided

        model_name = options.replace("bedrockcv-", "")
        return LLMWrapper(
            options,
            ChatBedrockConverse(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature
            )
        )

    elif options.startswith("ollama-"):
        from langchain_ollama import ChatOllama

        model_name = options.replace("ollama-", "")
        return LLMWrapper(
            options,
            ChatOllama(
                model=model_name,
                num_predict=max_tokens,  # maximum number of tokens to predict
                temperature=temperature,
                client_kwargs={
                    "timeout": float(os.environ["OLLAMA_TIMEOUT"])
                    if os.environ.get("OLLAMA_TIMEOUT") not in (None, "")
                    else None
                },
                # timeout in seconds (None = not configured)
            ).with_retry(
                stop_after_attempt=int(os.environ["OLLAMA_MAX_ATTEMPTS"])
                if os.environ.get("OLLAMA_MAX_ATTEMPTS") not in (None, "")
                else 1,
                # total attempts (1 initial + retries)
                wait_exponential_jitter=True,  # backoff with jitter
            )
        )

    elif options.startswith("llamaccp-server"):
        from langchain_openai import ChatOpenAI

        if options == "llamaccp-server":
            url = "http://localhost:8080/"
        else:
            try:
                port = int(options.split("llamaccp-server-")[-1])
                url = f"http://localhost:{port}/"
            except ValueError as e:
                raise ValueError(
                    f"Invalid port in options: '{options}'. Expected format 'llamaccp-server-[port]', for example 'llamaccp-server-8080'."
                ) from e

        return LLMWrapper(
            options,
            ChatOpenAI(
                base_url=url,
                api_key="abc",
                max_tokens=None,
                timeout=None,
                max_retries=2,
            )
        )

    elif options.startswith("together"):
        from langchain_openai import ChatOpenAI
        import os

        model_name_key = options.replace("together-", "")
        key = model_name_key if options is not None else DEFAULT_TOGETHER_AI_KEY
        model_name = _resolve_togetherai_model(key)

        return LLMWrapper(
            options,
            ChatOpenAI(
                base_url="https://api.together.xyz/v1",
                api_key=os.environ.get("TOGETHER_API_KEY"),
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=None,
                max_retries=2,
            )
        )

    elif options.startswith("offline"):
        return None

    elif options == "mock":
        return MockLLM(max_tokens=max_tokens)

    elif options.startswith("mock"):
        return MockLLM(
            options[5:], max_tokens=max_tokens
        )  # Pass model name after 'mock'

    else:
        raise ValueError(
            f"Invalid options format: '{options}'. Expected prefix 'openai-', 'google-', 'ollama-', 'bedrock-', 'llamaccp-server', 'together-', or 'offline'."
        )


class MockLLM:
    # A mock LLM class for testing purposes

    def __init__(self, model_name=None, max_tokens=8):
        if model_name is None or model_name == "":
            print("[MockLLM] No model name provided; using default mock behavior.")
            self.model = None
            self.max_tokens = max_tokens

        else:
            print("[MockLLM] Initializing mock LLM with model name:", model_name)
            self.model = get_llm(model_name, max_tokens=max_tokens)

    def invoke(self, messages):
        if self.model:
            response = self.model.invoke(messages)

        else:
            response = "This is a mock response from the LLM."

            if self.max_tokens is not None:
                response = response[: self.max_tokens]

        print("[Mock LLM] Message:", messages)
        print(
            "[Mock LLM] Response:",
            response,
            (" ======== " + response.content) if hasattr(response, "content") else "",
        )
        print("--------------------------------")

        return response
