"""api/index.py's full source as one text, with each _load_part("name") line
replaced by that part (api/_parts/name.py), in load order: the file as it
was before Stage 7.2 split it. For tests that check or slice the source."""
import os, re

API = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api")


def full_source():
    src = open(os.path.join(API, "index.py"), encoding="utf-8").read()
    return re.sub(r'^_load_part\("(\w+)"\).*$',
                  lambda m: open(os.path.join(API, "_parts", m.group(1) + ".py"), encoding="utf-8").read(),
                  src, flags=re.M)
