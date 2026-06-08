from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from evals.mira_eval.product_compare import run_competitive_benchmark


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Mira against GPT-backed LLM product baselines.")
    parser.add_argument("--dataset", default="evals/datasets/mira_competitive.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:3101")
    parser.add_argument("--targets", default="mira,generic_gpt,travel_gpt")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    output_json = args.output_json or str(Path("reports") / "evals" / "mira-competitive-latest.json")
    output_md = args.output_md or str(Path("reports") / "evals" / "mira-competitive-latest.md")
    report = asyncio.run(
        run_competitive_benchmark(
            dataset_path=args.dataset,
            base_url=args.base_url,
            targets=targets,
            model=args.model,
            output_json_path=output_json,
            output_markdown_path=output_md,
            limit=args.limit,
        )
    )
    print(
        "Mira competitive eval complete: "
        f"cases={report['summary']['case_count']} targets={','.join(report['summary']['targets'])} "
        f"json={output_json} md={output_md}"
    )


if __name__ == "__main__":
    main()
