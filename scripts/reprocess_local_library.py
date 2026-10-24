"""Reprocess registered large/timing-limited imports without duplicating assets."""
import json
import os
from pathlib import Path


def main():
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    from phiaimadeos.reprocess_library import reprocess_library
    report = reprocess_library(progress=lambda item: print(json.dumps(item, ensure_ascii=False), flush=True))
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
