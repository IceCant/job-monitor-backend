from html import unescape
from lxml import html


def html_to_text(content: str | None) -> str | None:
    if not content:
        return None

    decoded = content

    for _ in range(3):
        next_value = unescape(decoded)

        if next_value == decoded:
            break

        decoded = next_value

    try:
        root = html.fromstring(decoded)
        text = root.text_content()
    except (ValueError, TypeError):
        return decoded.strip() or None

    cleaned = "\n".join(
        line.strip()
        for line in text.splitlines()
        if line.strip()
    )

    return cleaned or None