"""
Unified LLM client -- supports multiple providers through a single interface.

Providers:
  - groq             : Groq API (free, fast inference)
  - openai           : OpenAI API (GPT-4o, GPT-4-turbo, etc.)
  - anthropic        : Anthropic API (Claude Opus, Sonnet, Haiku)
  - azure_openai     : Azure OpenAI Service (GPT models via Azure)
  - (azure_openai also works for Claude on Azure — set LLM_MODEL to claude model name)
  - bedrock          : AWS Bedrock native (Claude via Anthropic SDK + AWS credentials)
  - bedrock_openai   : AWS Bedrock via OpenAI-compatible proxy (enterprise gateways)
  - ollama           : Local Ollama server
  - custom           : Any OpenAI-compatible API (set LLM_BASE_URL)

Configuration (environment variables):
  REQUIRED:
    LLM_PROVIDER  = provider name (see above)
    LLM_API_KEY   = API key (not needed for bedrock, ollama)

  OPTIONAL:
    LLM_MODEL     = model name override (each provider has a sensible default)
    LLM_BASE_URL  = custom endpoint URL (required for: custom, bedrock_openai, azure_anthropic)

  AZURE OPENAI (LLM_PROVIDER=azure_openai):
    AZURE_OPENAI_ENDPOINT    = https://your-resource.openai.azure.com/  (REQUIRED)
    AZURE_OPENAI_API_VERSION = 2024-12-01-preview                       (optional, has default)
    AZURE_OPENAI_DEPLOYMENT  = your-deployment-name                     (optional)

  AZURE + CLAUDE (LLM_PROVIDER=azure_openai):
    Same as Azure OpenAI above, but set LLM_MODEL to a Claude model name.
    Azure wraps Claude in the same OpenAI Chat Completions format as GPT.
    LLM_MODEL     = claude-sonnet-4-20250514     (set to your Claude deployment's model name)

  AWS BEDROCK NATIVE (LLM_PROVIDER=bedrock):
    AWS_REGION = us-east-1  (optional, defaults to us-east-1)
    Uses AWS credential chain: env vars, ~/.aws/credentials, IAM role

  AWS BEDROCK VIA PROXY (LLM_PROVIDER=bedrock_openai):
    LLM_BASE_URL  = https://your-bedrock-proxy.com/v1  (REQUIRED - OpenAI-compatible proxy)
    LLM_API_KEY   = your-proxy-api-key                  (REQUIRED)
    LLM_MODEL     = anthropic.claude-sonnet-4-20250514-v1:0  (optional, has default)
"""

import os
import re

# SSL verification — configurable via .env (default: enabled)
_SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() not in ("false", "0", "no")

# Provider presets: (base_url, default_model, display_label)
PROVIDER_PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "label": "Groq",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "needs_key": True,
        "key_hint": "gsk_...",
        "key_url": "https://console.groq.com/keys",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "label": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "needs_key": True,
        "key_hint": "sk-...",
        "key_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "base_url": None,
        "default_model": "claude-sonnet-4-20250514",
        "label": "Anthropic",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-5-20251001"],
        "needs_key": True,
        "key_hint": "sk-ant-...",
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "azure_openai": {
        "base_url": None,  # set via AZURE_OPENAI_ENDPOINT
        "default_model": "gpt-4o",
        "label": "Azure OpenAI",
        # Works for BOTH GPT and Claude on Azure (Azure wraps all models in OpenAI format)
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
                    "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
        "needs_key": True,
        "key_hint": "Azure API key or use Azure AD token",
        "key_url": "https://portal.azure.com",
    },
    # NOTE: azure_anthropic removed — use azure_openai for Claude on Azure
    # (Azure wraps Claude in OpenAI Chat Completions format, same as GPT)
    "azure_foundry": {
        "base_url": None,  # set via AZURE_FOUNDRY_ENDPOINT or LLM_BASE_URL
        "default_model": "claude-sonnet-4-20250514",
        "label": "Azure AI Foundry",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514",
                    "gpt-4o", "gpt-4o-mini"],
        "needs_key": True,
        "key_hint": "Azure AI Foundry API key",
        "key_url": "https://ai.azure.com",
    },
    "bedrock": {
        "base_url": None,
        "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
        "label": "AWS Bedrock",
        "models": [
            "anthropic.claude-sonnet-4-20250514-v1:0",
            "anthropic.claude-opus-4-20250514-v1:0",
            "anthropic.claude-haiku-4-5-20251001-v1:0",
        ],
        "needs_key": False,  # uses AWS credential chain
        "key_hint": "Uses AWS credentials (env vars, ~/.aws/credentials, IAM role)",
        "key_url": "https://console.aws.amazon.com/bedrock",
    },
    "bedrock_openai": {
        "base_url": None,  # set via LLM_BASE_URL (OpenAI-compatible Bedrock proxy)
        "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
        "label": "AWS Bedrock (proxy)",
        "models": [
            "anthropic.claude-sonnet-4-20250514-v1:0",
            "anthropic.claude-opus-4-20250514-v1:0",
            "anthropic.claude-haiku-4-5-20251001-v1:0",
        ],
        "needs_key": True,
        "key_hint": "API key for your Bedrock proxy gateway",
        "key_url": "https://console.aws.amazon.com/bedrock",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1",
        "label": "Ollama (local)",
        "models": ["llama3.1", "llama3.2", "mistral", "gemma2", "qwen2.5"],
        "needs_key": False,
        "key_hint": "",
        "key_url": "",
    },
}

SUPPORTED_PROVIDERS = sorted(set(list(PROVIDER_PRESETS.keys()) + ["custom"]))


class LLMClient:
    """
    Unified async LLM client. Call `chat()` with standard OpenAI-style messages.
    Works with any supported provider -- the caller doesn't need to know which.
    """

    def __init__(self, provider: str = "", api_key: str = "", model: str = "",
                 base_url: str = ""):
        """
        Create an LLM client. If params are empty, reads from environment variables.
        Falls back to GROQ_API_KEY for backward compatibility.
        """
        self.provider = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
        self.api_key = (api_key or os.getenv("LLM_API_KEY", "")).strip()
        self.model = (model or os.getenv("LLM_MODEL", "")).strip()
        self._base_url = (base_url or os.getenv("LLM_BASE_URL", "")).strip()

        # Token usage tracking
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_api_calls: int = 0

        if not self.api_key:
            # Backwards compatibility: fall back to GROQ_API_KEY
            self.api_key = os.getenv("GROQ_API_KEY", "").strip()
            if self.api_key and not self.provider:
                self.provider = "groq"

        if not self.provider:
            self.provider = "groq"

        if not self.api_key and self.provider not in ("ollama", "bedrock"):
            raise ValueError(
                "LLM_API_KEY not set. "
                "See README.md for configuration instructions."
            )

        if self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "azure_openai":
            self._init_azure_openai()
        elif self.provider == "azure_foundry":
            # Azure AI Foundry — auto-detect Anthropic-native vs OpenAI-compatible
            # Support multiple env var names for flexibility
            foundry_resource = os.getenv("AZURE_FOUNDRY_RESOURCE", "").strip()
            foundry_endpoint = (
                os.getenv("AZURE_FOUNDRY_ENDPOINT", "").strip()
                or os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
                or self._base_url
            )
            # If resource name provided, construct endpoint
            if foundry_resource and not foundry_endpoint:
                foundry_endpoint = f"https://{foundry_resource}.services.ai.azure.com/anthropic/v1"
            if not foundry_endpoint:
                raise ValueError(
                    "Set AZURE_FOUNDRY_ENDPOINT or AZURE_OPENAI_ENDPOINT "
                    "(e.g., https://your-resource.services.ai.azure.com/anthropic/v1) "
                    "when LLM_PROVIDER=azure_foundry."
                )
            # Auto-detect: if endpoint contains /anthropic/, use Anthropic SDK
            if "/anthropic/" in foundry_endpoint.lower():
                base = foundry_endpoint.rstrip("/")
                # Strip /messages suffix — Anthropic SDK appends it automatically
                if base.endswith("/messages"):
                    base = base[:-len("/messages")]
                self._init_azure_foundry_anthropic(base)
            else:
                # OpenAI-compatible (for GPT models on Foundry)
                self._base_url = foundry_endpoint.rstrip("/")
                self._init_openai_compat()
        elif self.provider == "bedrock":
            self._init_bedrock()
        elif self.provider == "bedrock_openai":
            # AWS Bedrock via OpenAI-compatible proxy — use OpenAI SDK with custom base URL
            if not self._base_url:
                raise ValueError(
                    "LLM_BASE_URL must be set when LLM_PROVIDER=bedrock_openai. "
                    "This should be your organization's OpenAI-compatible Bedrock proxy "
                    "(e.g., https://your-bedrock-proxy.company.com/v1)."
                )
            self._init_openai_compat()
        else:
            self._init_openai_compat()

    def _init_openai_compat(self):
        """Initialize for any OpenAI-compatible provider (Groq, OpenAI, Ollama, proxies)."""
        from openai import AsyncOpenAI

        if self.provider in ("custom", "bedrock_openai", "azure_foundry"):
            if not self._base_url:
                raise ValueError(f"LLM_BASE_URL must be set when LLM_PROVIDER={self.provider}")
            base_url = self._base_url
            preset = PROVIDER_PRESETS.get(self.provider, {})
            default_model = preset.get("default_model", "gpt-4o")
        elif self.provider in PROVIDER_PRESETS:
            preset = PROVIDER_PRESETS[self.provider]
            base_url = preset["base_url"]
            default_model = preset["default_model"]
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER: '{self.provider}'. "
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
            )

        if not self.model:
            self.model = default_model

        client_kwargs = dict(base_url=base_url, api_key=self.api_key or "ollama")
        if not _SSL_VERIFY:
            import httpx
            client_kwargs["http_client"] = httpx.AsyncClient(verify=False)
        self._client = AsyncOpenAI(**client_kwargs)
        self._is_anthropic = False

    def _init_anthropic(self):
        """Initialize for Anthropic (Claude)."""
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for LLM_PROVIDER=anthropic. "
                "Install it with: pip install anthropic"
            )

        if not self.model:
            self.model = PROVIDER_PRESETS["anthropic"]["default_model"]

        self._client = AsyncAnthropic(api_key=self.api_key)
        self._is_anthropic = True

    def _init_azure_openai(self):
        """Initialize for Azure OpenAI Service."""
        try:
            from openai import AsyncAzureOpenAI
        except ImportError:
            raise ImportError(
                "The 'openai' package >= 1.0 is required for Azure OpenAI. "
                "Install it with: pip install openai"
            )

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview").strip()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()

        if not endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT must be set when LLM_PROVIDER=azure_openai. "
                "Example: https://your-resource.openai.azure.com/"
            )

        # Azure routes by deployment name — when set, use it as the model parameter
        if deployment:
            self.model = deployment
        elif not self.model:
            self.model = PROVIDER_PRESETS["azure_openai"]["default_model"]

        azure_kwargs = dict(
            azure_endpoint=endpoint,
            api_version=api_version,
            api_key=self.api_key,
            azure_deployment=deployment or None,
        )
        if not _SSL_VERIFY:
            import httpx
            azure_kwargs["http_client"] = httpx.AsyncClient(verify=False)
        self._client = AsyncAzureOpenAI(**azure_kwargs)
        self._is_anthropic = False

    def _init_bedrock(self):
        """Initialize for AWS Bedrock (Claude via AWS account)."""
        try:
            from anthropic import AsyncAnthropicBedrock
        except ImportError:
            raise ImportError(
                "The 'anthropic[bedrock]' package is required for LLM_PROVIDER=bedrock. "
                "Install it with: pip install 'anthropic[bedrock]'"
            )

        region = os.getenv("AWS_REGION", "us-east-1").strip()

        if not self.model:
            self.model = PROVIDER_PRESETS["bedrock"]["default_model"]

        self._client = AsyncAnthropicBedrock(aws_region=region)
        self._is_anthropic = True  # Bedrock uses the same Anthropic message format

    def _init_azure_foundry_anthropic(self, endpoint: str):
        """Initialize for Azure AI Foundry using official AnthropicFoundry SDK."""
        try:
            from anthropic import AsyncAnthropicFoundry
        except ImportError:
            raise ImportError(
                "The 'anthropic' package >= 0.40.0 is required for Azure AI Foundry. "
                "Install/upgrade: pip install -U anthropic"
            )

        if not self.model:
            self.model = PROVIDER_PRESETS["azure_foundry"]["default_model"]

        # Extract resource name from endpoint URL if full URL provided
        # e.g., https://my-resource.services.ai.azure.com/anthropic/v1/messages
        #   → resource = "my-resource"
        resource_match = re.match(r"https://([^.]+)\.services\.ai\.azure\.com", endpoint)

        client_kwargs = dict(api_key=self.api_key)

        if resource_match:
            # Use resource name — SDK constructs the correct URL
            client_kwargs["resource"] = resource_match.group(1)
        else:
            # Fallback: pass full URL as base_url
            base = endpoint.rstrip("/")
            if base.endswith("/messages"):
                base = base[:-len("/messages")]
            if "/anthropic/" in base and not base.endswith("/anthropic"):
                base = base[:base.index("/anthropic/") + len("/anthropic")]
            client_kwargs["base_url"] = base

        if not _SSL_VERIFY:
            import httpx
            client_kwargs["http_client"] = httpx.AsyncClient(verify=False)

        self._client = AsyncAnthropicFoundry(**client_kwargs)
        self._is_anthropic = True  # Routes to _chat_anthropic() → messages.create()

    async def chat(self, messages: list[dict], max_tokens: int = 1000,
                   temperature: float | None = None) -> str:
        """
        Send a chat completion request and return the response text.

        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": "..."}
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0 = deterministic). None = provider default.

        Returns:
            The assistant's response text.
        """
        if self._is_anthropic:
            return await self._chat_anthropic(messages, max_tokens, temperature)
        return await self._chat_openai(messages, max_tokens, temperature)

    async def _chat_openai(self, messages: list[dict], max_tokens: int,
                           temperature: float | None = None) -> str:
        kwargs = dict(model=self.model, max_tokens=max_tokens, messages=messages)
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            err_str = str(e).lower()
            if "unknown_model" in err_str or "unknown model" in err_str:
                raise ValueError(
                    f"Endpoint rejected model '{self.model}'. "
                    f"For Azure: set AZURE_OPENAI_DEPLOYMENT to your deployment name "
                    f"(run: curl YOUR_ENDPOINT/openai/models?api-version=2024-12-01-preview "
                    f"-H 'api-key: YOUR_KEY' to list available models). "
                    f"For proxies: check what model names your gateway accepts."
                ) from e
            raise
        # Track token usage
        self.total_api_calls += 1
        if hasattr(response, "usage") and response.usage:
            self.total_prompt_tokens += getattr(response.usage, "prompt_tokens", 0)
            self.total_completion_tokens += getattr(response.usage, "completion_tokens", 0)
        return response.choices[0].message.content.strip()

    async def _chat_anthropic(self, messages: list[dict], max_tokens: int,
                              temperature: float | None = None) -> str:
        # Anthropic separates the system prompt from messages
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            else:
                user_messages.append(msg)

        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=user_messages,
        )
        if system_text.strip():
            kwargs["system"] = system_text.strip()
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._client.messages.create(**kwargs)
        # Track token usage
        self.total_api_calls += 1
        if hasattr(response, "usage") and response.usage:
            self.total_prompt_tokens += getattr(response.usage, "input_tokens", 0)
            self.total_completion_tokens += getattr(response.usage, "output_tokens", 0)
        return response.content[0].text.strip()

    async def chat_vision(self, prompt: str, image_bytes: bytes, media_type: str,
                          max_tokens: int = 2000, temperature: float | None = 0) -> str:
        """Send a single image + text prompt to a vision-capable LLM.

        Builds the correct multimodal content block for Anthropic vs OpenAI
        formats internally — callers don't need to know which provider is in use.

        Args:
            prompt: Text instructions for the model.
            image_bytes: Raw image bytes (PNG, JPEG, etc.)
            media_type: MIME type, e.g. "image/png", "image/jpeg".
            max_tokens: Max response tokens.
            temperature: Sampling temperature (0 = deterministic).
        """
        import base64
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")

        if self._is_anthropic:
            content = [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]

        return await self.chat(
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

    @property
    def token_usage(self) -> dict:
        """Return accumulated token usage stats."""
        return {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "api_calls": self.total_api_calls,
        }

    def display_name(self) -> str:
        """Human-readable string for console output."""
        preset = PROVIDER_PRESETS.get(self.provider)
        label = preset["label"] if preset else self.provider
        return f"{self.model} via {label}"
