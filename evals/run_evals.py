#!/usr/bin/env python3
"""Стенд оценки скилла fable5-style.

Прогоняет задачи из evals/tasks.yaml через Anthropic API и считает
программируемые проверки. Сравнение «скилл включён / выключен» — два запуска:

    export ANTHROPIC_API_KEY=...
    python evals/run_evals.py --model claude-opus-4-8 --skill on  --repeats 3
    python evals/run_evals.py --model claude-opus-4-8 --skill off --repeats 3

Самопроверка стенда без API (гоняется в CI):

    python evals/run_evals.py --dry-run

В dry-run каждый sample_ok из tasks.yaml обязан пройти проверки своей задачи,
а пустой ответ — провалить их: так стенд доказывает, что умеет и засчитывать,
и заваливать.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"


def load_skill_prompt() -> str:
    parts = [(ROOT / "SKILL.md").read_text(encoding="utf-8")]
    for p in sorted((ROOT / "references").glob("*.md")):
        parts.append(
            f'\n\n<reference file="references/{p.name}">\n'
            f"{p.read_text(encoding='utf-8')}\n</reference>"
        )
    return "".join(parts)


def call_api(model: str, system: str, prompt: str) -> str:
    body = {
        "model": model,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return "".join(b["text"] for b in data["content"] if b["type"] == "text")


def extract_python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, re.S)


def run_checks(answer: str, checks: dict) -> list[str]:
    """Возвращает список проваленных проверок (пустой = все прошли)."""
    failures = []
    for pattern in checks.get("must_match", []):
        if not re.search(pattern, answer, re.I):
            failures.append(f"must_match не найден: {pattern}")
    for pattern in checks.get("forbidden", []):
        if re.search(pattern, answer, re.I):
            failures.append(f"forbidden найден: {pattern}")
    lead = answer[:300]
    for pattern in checks.get("lead_no", []):
        if re.search(pattern, lead, re.I):
            failures.append(f"вода в начале ответа: {pattern}")
    if checks.get("code_syntax"):
        blocks = extract_python_blocks(answer)
        if not blocks:
            failures.append("code_syntax: в ответе нет блока ```python")
        for i, block in enumerate(blocks):
            try:
                compile(block, f"<block{i}>", "exec")
            except SyntaxError as e:
                failures.append(f"code_syntax: блок {i} не компилируется: {e.msg}")
    return failures


def dry_run(tasks: list[dict]) -> int:
    """Самопроверка стенда: sample_ok проходит, пустой ответ — нет."""
    broken = 0
    for task in tasks:
        ok_failures = run_checks(task["sample_ok"], task["checks"])
        if ok_failures:
            broken += 1
            print(f"FAIL {task['id']}: sample_ok не проходит собственные проверки:")
            for f in ok_failures:
                print("   -", f)
        if not run_checks("", task["checks"]):
            broken += 1
            print(f"FAIL {task['id']}: пустой ответ проходит проверки — они ничего не проверяют")
    if broken:
        print(f"\nСтенд неисправен: {broken} проблем(ы).")
        return 1
    print(f"OK: стенд исправен — {len(tasks)} задач, sample_ok проходят, пустые ответы валятся.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--skill", choices=["on", "off"], default="on")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only", help="запустить одну задачу по id")
    ap.add_argument("--dry-run", action="store_true", help="самопроверка стенда без API")
    ap.add_argument("--report", default=None, help="путь к JSON-отчёту")
    args = ap.parse_args()

    tasks = yaml.safe_load((ROOT / "evals" / "tasks.yaml").read_text(encoding="utf-8"))
    if args.only:
        tasks = [t for t in tasks if t["id"] == args.only]
        if not tasks:
            print(f"нет задачи с id={args.only}")
            return 2

    if args.dry_run:
        return dry_run(tasks)

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("Нужен ANTHROPIC_API_KEY (или --dry-run для самопроверки стенда).")
        return 2

    system = load_skill_prompt() if args.skill == "on" else ""
    results = []
    passed_total = 0
    for task in tasks:
        task_passes = 0
        last_failures: list[str] = []
        for _ in range(args.repeats):
            answer = call_api(args.model, system, task["prompt"])
            failures = run_checks(answer, task["checks"])
            if failures:
                last_failures = failures
            else:
                task_passes += 1
        ok = task_passes == args.repeats
        passed_total += ok
        mark = "PASS" if ok else f"FAIL ({task_passes}/{args.repeats})"
        print(f"{mark:12} {task['id']} [{task['category']}]")
        for f in last_failures:
            print("   -", f)
        results.append({"id": task["id"], "category": task["category"],
                        "passes": task_passes, "repeats": args.repeats,
                        "failures": last_failures})

    print(f"\nИтог: {passed_total}/{len(tasks)} задач стабильно зелёные "
          f"(модель {args.model}, скилл {args.skill}, повторов {args.repeats}).")
    if args.report:
        Path(args.report).write_text(json.dumps(
            {"model": args.model, "skill": args.skill, "results": results},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON-отчёт: {args.report}")
    return 0 if passed_total == len(tasks) else 1


if __name__ == "__main__":
    sys.exit(main())
