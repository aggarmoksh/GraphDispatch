from pathlib import Path
from common import connect

db = connect()
g = db.select_graph("probe_procs")
res = g.query("CALL dbms.procedures()")
names = sorted(" | ".join(str(c) for c in row) for row in res.result_set)
Path(__file__).with_name("procedures.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
print(res.header)
for n in names:
    if n.startswith("algo."):
        print(n)
print(len(names), "procedures")
