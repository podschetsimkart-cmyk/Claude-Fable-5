#!/usr/bin/env bash
# PostToolUse-хук (Edit|Write): после правки .py-файла гоняет ruff и проверку
# синтаксиса. Код выхода 2 возвращает сообщение модели — она обязана починить,
# прежде чем двигаться дальше. Дисциплина «код запускается» перестаёт быть
# просьбой и становится механикой.
set -u

input=$(cat)
file=$(printf '%s' "$input" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

if ! out=$(python3 -m py_compile "$file" 2>&1); then
  echo "Файл не компилируется — исправь до продолжения: $out" >&2
  exit 2
fi

if command -v ruff >/dev/null 2>&1; then
  if ! out=$(ruff check "$file" 2>&1); then
    echo "ruff нашёл проблемы — исправь: $out" >&2
    exit 2
  fi
fi
exit 0
