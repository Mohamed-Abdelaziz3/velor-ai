"""Runtime selection for customer-facing conversation engines."""

import os


def get_whatsapp_response_engine() -> str:
    """Return the explicit WhatsApp engine, defaulting new deployments to V2."""
    value = os.getenv("WHATSAPP_RESPONSE_ENGINE", "v2").strip().casefold()
    return value if value in {"v1", "v2"} else "v2"


def get_external_api_response_engine() -> str:
    """Return the external API engine; V1 remains an explicit rollback only."""
    value = os.getenv("EXTERNAL_API_RESPONSE_ENGINE", "v2").strip().casefold()
    return value if value in {"v1", "v2"} else "v2"
