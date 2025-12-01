from typing import Dict

SUPPORTED_LLM_MODELS = [
    "openai-gpt-4.1-mini",
    "openai-gpt-4o-mini",

    "ollama-phi4-mini",
    "ollama-gemma3",
    "ollama-llama3.2",

    "bedrock-us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "bedrock-us.meta.llama4-scout-17b-instruct-v1:0",

    "llamaccp-server",
    "llamaccp-server-[port]",

    "together-gemma2-8b",
    "together-gemma2-27b",
    "together-llama4-maverick-fp8", 
    "together-llama4-scout",
    "together-llama31-8b",
    "together-llama31-70b", 
    "together-llama31-405b", 
    "together-llama33-70b", 
    "together-mixtral-8x7b",
    "together-mixtral-8x22b",
    "together-qwen3-235b-fp8",

    "offline",
]

SUPPORTED_PREFIXES = ["openai-", "ollama-", "bedrock-", "llamaccp-server-", "together-"]

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

def _resolve_model(key: str) -> str:
    """
    Convert a shorthand key to the full model identifier.
    Raises ValueError for unknown keys.
    """
    if key not in TOGETHER_AI_MODEL_MAP:
        valid = ", ".join(TOGETHER_AI_MODEL_MAP.keys())
        raise ValueError(f"Unknown model key '{key}'. Valid keys: {valid}")
    return TOGETHER_AI_MODEL_MAP[key]

def get_llm(options=None):
    """
    Initialize and return the appropriate LLM based on options.
    """
    if (options not in SUPPORTED_LLM_MODELS and not any(options.startswith(prefix) for prefix in SUPPORTED_PREFIXES)):
        raise ValueError(
            f"Unsupported LLM option: '{options}'. "
            f"Supported options: {SUPPORTED_LLM_MODELS}"
        )

    if options.startswith("openai-"):
        from langchain_openai import ChatOpenAI

        model_name = options.replace("openai-", "")
        return ChatOpenAI(
            model=model_name,
            max_tokens=8,
            temperature=0,
            timeout=None,
            max_retries=2,
        )

    elif options.startswith("ollama-"):
        from langchain_ollama import ChatOllama

        model_name = options.replace("ollama-", "")
        return ChatOllama(
            model=model_name,
            max_tokens=8,
            temperature=0,
            timeout=None,
            max_retries=2,
        )

    elif options.startswith("bedrock-"):
        from langchain_aws import ChatBedrock

        model_name = options.replace("bedrock-", "")
        return ChatBedrock(
            model=model_name,
            max_tokens=8,
            temperature=0
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

        return ChatOpenAI(
            base_url=url,
            api_key="abc",
            max_tokens=None,
            timeout=None,
            max_retries=2,
        )

    elif options.startswith("together"):
        from langchain_together import ChatTogether   
   
        model_name_key = options.replace("together-", "")
        key = model_name_key if options is not None else DEFAULT_TOGETHER_AI_KEY
        model_name = _resolve_model(key)
        
        return ChatTogether(
            model=model_name,
            max_tokens=8,
            temperature=0,
            timeout=None,
            max_retries=2,
        )

    elif options.startswith("offline"):
        return None

    else:
        raise ValueError(
            f"Invalid options format: '{options}'. Expected prefix 'openai-', 'ollama-', 'bedrock-', 'llamaccp-server', 'together-', or 'offline'."
        )
