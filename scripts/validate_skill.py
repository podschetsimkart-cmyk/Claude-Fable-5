#!/usr/bin/env python3
"""Валидация скилла fable5-style: YAML-шапка, лимиты Claude, маршрутизация ↔ файлы.

Запуск локально: python scripts/validate_skill.py
В CI запускается на каждый пуш и pull request.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []

text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

fm = {}
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
if not m:
    errors.append("SKILL.md: не найдена YAML-шапка (--- ... ---)")
else:
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        errors.append(f"YAML-шапка не парсится: {e}")

name = str(fm.get("name", ""))
desc = str(fm.get("description", ""))
if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
    errors.append(f"name {name!r}: допустимы только [a-z0-9-], длина 1–64")
if not desc:
    errors.append("description отсутствует или пуст")
elif len(desc) > 1024:
    errors.append(f"description: {len(desc)} символов, лимит Claude — 1024")

words = len(text.split())
if words > 5000:
    errors.append(f"SKILL.md: {words} слов, рекомендация Anthropic — до 5000")

if not re.search(r"^Версия: \d+\.\d+ \(\d{4}-\d{2}-\d{2}\)$", text, re.M):
    errors.append("SKILL.md: нет строки версии вида «Версия: X.Y (ГГГГ-ММ-ДД)»")

mentioned = set(re.findall(r"`references/([\w-]+\.md)`", text))
actual = {p.name for p in (ROOT / "references").glob("*.md")}
for f in sorted(mentioned - actual):
    errors.append(f"SKILL.md ссылается на несуществующий references/{f}")
for f in sorted(actual - mentioned):
    errors.append(f"references/{f} не упомянут в SKILL.md — файл-сирота")

if errors:
    print("FAIL — скилл не пройдёт установку или собран неконсистентно:")
    for e in errors:
        print(" -", e)
    sys.exit(1)

version = re.search(r"^Версия: (.+)$", text, re.M).group(1)
print(
    f"OK: версия {version}; name и description валидны "
    f"({len(desc)}/1024 символов); {len(actual)} справочников, все пути сходятся."
)
