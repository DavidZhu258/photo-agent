from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from evals.mira_eval.runner import run_eval_suite


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mira product eval suites.")
    parser.add_argument("--dataset", default="evals/datasets/mira_smoke.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:3101")
    parser.add_argument("--output", default=None)
    parser.add_argument("--judge-mode", choices=["off", "auto", "required"], default="auto")
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    output = args.output or _default_output_path()
    result = asyncio.run(
        run_eval_suite(
            dataset_path=args.dataset,
            base_url=args.base_url,
            output_path=output,
            judge_mode=args.judge_mode,
            model=args.model,
        )
    )
    summary = result.summary
    print(
        f"Mira eval complete: {summary['passed']}/{summary['total']} passed "
        f"({summary['pass_rate']:.0%}); output={output}"
    )
    if summary["failed"]:
        raise SystemExit(1)


def _default_output_path() -> str:
    return str(Path("reports") / "evals" / "mira-eval-latest.json")


if __name__ == "__main__":
    main()
