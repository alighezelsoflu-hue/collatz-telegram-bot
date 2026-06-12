from io import BytesIO
from typing import List


def split_long_text(text: str, limit: int = 3500) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    return chunks


def text_to_file(text: str, filename: str) -> BytesIO:
    output = BytesIO()
    output.write(text.encode("utf-8"))
    output.seek(0)
    output.name = filename
    return output