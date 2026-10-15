import re
from pathlib import Path

def load_queries():
    text = (Path(__file__).with_name("queries.cypher")).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"-- \[(\w+)\][^\n]*\n(.*?);", text, re.S):
        out[m.group(1)] = m.group(2).strip()
    return out
