"""python -m ocr_feedback export ... (score, pick and replay come in later phases)."""

import argparse
import contextlib
import importlib
import sys

from .export import export_snapshot
from .profile import load_profile
from .store import FeedbackReader


def load_adapter(spec: str, args: dict):
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise SystemExit(f"--adapter must be module:callable, got {spec!r}")
    return getattr(importlib.import_module(module_name), attr)(**args)


def _pairs(items) -> dict:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"--adapter-arg must be key=value, got {item!r}")
        out[key] = value
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ocr_feedback")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="write a dataset snapshot")
    export.add_argument("--profile", required=True)
    export.add_argument("--feedback-db", default=None,
                        help="a COPY of the capture database (optional)")
    export.add_argument("--adapter", required=True, help="module:callable -> TruthSource")
    export.add_argument("--adapter-arg", action="append", default=[], metavar="KEY=VALUE")
    export.add_argument("--out", required=True)
    export.add_argument("--label", default=None)
    args = parser.parse_args(argv)

    if args.command == "export":
        if "" not in sys.path:
            sys.path.insert(0, "")
        profile = load_profile(args.profile)
        truth = load_adapter(args.adapter, _pairs(args.adapter_arg))
        with contextlib.ExitStack() as stack:
            close = getattr(truth, "close", None)
            if close:
                stack.callback(close)
            reader = FeedbackReader(args.feedback_db)
            stack.callback(reader.close)
            folder = export_snapshot(profile, truth, reader, args.out, label=args.label)
        print(folder)
    return 0
