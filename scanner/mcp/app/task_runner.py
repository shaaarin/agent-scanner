"""One engine task per disposable interpreter; stdin contains its config."""
import json
import sys
from pathlib import Path

from app.adapters import scan


def main():
    work, report = map(Path, sys.argv[1:])
    try:
        outcome = {"result": scan(json.load(sys.stdin), work)}
    except Exception as exc:
        outcome = {"error": str(exc)}
    report.write_text(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
