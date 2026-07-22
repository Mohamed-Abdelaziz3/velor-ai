import logging

log = logging.getLogger(__name__)

def repair_mojibake(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    try:
        # Check if the text contains characters typical of UTF-8 mojibake interpreted as CP1252/Latin-1
        if any(char in text for char in "ØÙÐÑÃÂ"):
            # Try to recover UTF-8 bytes from cp1252 or latin-1 encoding
            try:
                recovered = text.encode("cp1252").decode("utf-8")
                return recovered
            except (UnicodeEncodeError, UnicodeDecodeError):
                recovered = text.encode("latin-1").decode("utf-8")
                return recovered
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        log.debug("Failed to repair suspected mojibake '%s': %s", text, e)
    return text
