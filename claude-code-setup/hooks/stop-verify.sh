#!/usr/bin/env bash
# Stop-хук: перед завершением хода прогоняет тесты проекта (если они есть).
# Тесты красные — ход не завершается, модель получает вывод и обязана чинить.
# Это принудительная версия правила «проверено = запущено».
set -u

input=$(cat)
# Защита от бесконечного цикла: если хук уже останавливал этот ход — выходим.
active=$(printf '%s' "$input" | python3 -c "import json,sys; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null)
[ "$active" = "True" ] && exit 0

dir="${CLAUDE_PROJECT_DIR:-.}"
[ -d "$dir/tests" ] || exit 0
command -v pytest >/dev/null 2>&1 || exit 0

# Без пайпа: статус pytest не должен затираться статусом tail
out=$(cd "$dir" && pytest -q -x 2>&1)
if [ $? -ne 0 ]; then
  echo "Тесты падают — почини или честно доложи об этом в ответе: $(printf '%s' "$out" | tail -15)" >&2
  exit 2
fi
exit 0
