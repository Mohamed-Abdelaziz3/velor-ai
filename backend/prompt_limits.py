import os


# The runtime model is currently sent through Groq's llama-3.3-70b-versatile
# with room reserved for system scaffolding, bounded product/RAG context,
# conversation history, and the configured response token budget. There is no
# local tokenizer in this app, so persistence uses a conservative character
# ceiling and rejects unsupported prompts before they reach the database.
DEFAULT_COMPANY_SYSTEM_PROMPT_MAX_CHARS = 12000


def _read_limit() -> int:
    raw = os.getenv("COMPANY_SYSTEM_PROMPT_MAX_CHARS", "").strip()
    if not raw:
        return DEFAULT_COMPANY_SYSTEM_PROMPT_MAX_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_COMPANY_SYSTEM_PROMPT_MAX_CHARS
    return max(1000, value)


COMPANY_SYSTEM_PROMPT_MAX_CHARS = _read_limit()


def validate_company_system_prompt(prompt: str | None) -> str | None:
    if prompt is None:
        return prompt
    if len(prompt) > COMPANY_SYSTEM_PROMPT_MAX_CHARS:
        raise ValueError(
            f"system_prompt exceeds supported limit of {COMPANY_SYSTEM_PROMPT_MAX_CHARS} characters"
        )
    return prompt
