"""Rewrite non-ASCII characters in the built bundle as equivalent JavaScript \\uXXXX escapes."""
import collections
import sys

source = sys.argv[1]
text = open(source, encoding="utf-8").read()
chars = collections.Counter(c for c in text if ord(c) > 127)
print({"U+%04X" % ord(c): n for c, n in chars.items()})


def escape(character: str) -> str:
    code = ord(character)
    if code <= 0xFFFF:
        return "\\u%04x" % code
    code -= 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))


result = "".join(escape(c) if ord(c) > 127 else c for c in text)
with open(source.replace("tiptap.bundle.js", "tiptap.bundle.ascii.js"), "w", encoding="ascii", newline="\n") as out:
    out.write(result)
print("written", len(result))
