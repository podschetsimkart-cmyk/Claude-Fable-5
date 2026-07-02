# Google Apps Script — проверенные паттерны

## Главное правило: батчи, а не поячеечное чтение

`getValue()`/`setValue()` в цикле — отдельный API-вызов на каждую ячейку; скрипт упирается в таймаут 6 минут. Всегда: одно `getDataRange().getValues()`, обработка в памяти, одна запись `setValues()`.

## Скелет отчёта по расписанию

```javascript
const CONFIG = {
  sheetName: 'Данные',
  columns: { date: 'дата', amount: 'сумм' },  // ключевые слова из заголовков
};

function main() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30 * 1000)) return;  // прошлый запуск ещё идёт — выходим
  try {
    sendTelegram(buildReport());
  } catch (e) {
    console.error(e.stack || e);
    sendTelegram('⚠️ Ошибка скрипта: ' + e.message);  // молча не падать
  } finally {
    lock.releaseLock();
  }
}

function findColumns(headers) {
  const norm = headers.map(h => String(h).toLowerCase().trim());
  const idx = {};
  for (const [key, word] of Object.entries(CONFIG.columns)) {
    idx[key] = norm.findIndex(h => h.includes(word));
    if (idx[key] === -1) throw new Error('Не найдена колонка: ' + word);
  }
  return idx;
}

function buildReport() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.sheetName);
  if (!sheet) throw new Error('Лист не найден: ' + CONFIG.sheetName);
  const values = sheet.getDataRange().getValues();   // ОДНО чтение
  const col = findColumns(values[0]);
  const tz = Session.getScriptTimeZone();
  const today = Utilities.formatDate(new Date(), tz, 'dd.MM.yyyy');
  let total = 0;
  for (const row of values.slice(1)) {
    const cell = row[col.date];
    const date = cell instanceof Date
      ? Utilities.formatDate(cell, tz, 'dd.MM.yyyy')
      : String(cell).trim();
    if (date === today) total += Number(row[col.amount]) || 0;
  }
  return '<b>Отчёт за ' + today + '</b>\nСумма: ' + total;
}
```

- Не привязываться к буквам колонок — искать по ключевому слову в заголовке (`findColumns`); таблицу люди переставляют.
- Даты из ячеек приходят объектами `Date` — сравнивать через `Utilities.formatDate` в таймзоне скрипта, не строковым сравнением.
- `LockService` защищает от наложения запусков, когда прошлый триггер ещё не закончил.

## Отправка в Telegram (с разбиением длинных сообщений)

```javascript
function sendTelegram(text) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('BOT_TOKEN');
  const chatId = props.getProperty('CHAT_ID');
  for (let i = 0; i < text.length; i += 4000) {  // лимит Telegram — 4096
    const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ chat_id: chatId, text: text.slice(i, i + 4000), parse_mode: 'HTML' }),
      muteHttpExceptions: true,
    });
    if (resp.getResponseCode() !== 200) {
      console.error('Telegram error: ' + resp.getContentText());
    }
  }
}
```

Токен и chat_id — только в Script Properties (Настройки проекта → Свойства скрипта), не в коде.

## Диагностика распознавания колонок

Держать функцию, которую можно запустить руками и посмотреть в лог, какая колонка на что распозналась:

```javascript
function testRecognizeColumns() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.sheetName);
  const headers = sheet.getDataRange().getValues()[0];
  console.log(JSON.stringify(findColumns(headers)));
  console.log('Заголовки: ' + JSON.stringify(headers));
}
```

## Триггеры и лимиты

- Клок-триггеры: интерфейс «Триггеры» или `ScriptApp.newTrigger('main').timeBased().everyHours(1).create()`.
- Создавая триггер из кода, сначала удалить старые (`ScriptApp.getProjectTriggers()` + `deleteTrigger`), иначе они множатся.
- Лимиты (обычный аккаунт): выполнение до 6 мин; UrlFetch ~20 000/сутки; суммарное время триггеров 90 мин/сутки.
- Логи выполнения по триггеру — в разделе «Выполнения» редактора.
