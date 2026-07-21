/**
 * Эталонная копия скрипта, который реально живёт внутри гугл-таблицы
 * "Список клиентов на старт" (Extensions -> Apps Script).
 *
 * Обрабатывает два вида POST от GitHub Actions, различаемых полем action:
 *   - action отсутствует или "report_link": дописывает ссылку на готовый
 *     отчёт + время в строку клиента (после месячной генерации).
 *   - action === "edit_status": проставляет статус ("применено"/"ошибка")
 *     + время + текст ошибки в строку вкладки "Правки" (после того, как
 *     ручная правка Лизы была применена или отклонена).
 *
 * Секрет хранится в Script Properties (Project Settings -> Script
 * Properties), НЕ в самом коде, чтобы он не был виден даже тем, у кого есть
 * доступ на просмотр скрипта.
 *
 * Разовая установка (делает тот, у кого есть право редактировать таблицу):
 *   1. В таблице: Extensions -> Apps Script.
 *   2. Вставить содержимое этого файла в Code.gs.
 *   3. Project Settings (шестерёнка слева) -> Script Properties -> Add property:
 *        key = SHARED_SECRET, value = <тот же секрет, что уйдёт в GitHub
 *        секрет SHEET_SHARED_SECRET>.
 *   4. Deploy -> New deployment -> тип "Web app" -> Execute as "Me",
 *      Who has access "Anyone" -> Deploy -> скопировать URL, оканчивающийся
 *      на /exec.
 *   5. Этот URL -> GitHub секрет SHEET_WEBAPP_URL в репозитории ads-reports-hub/reports.
 *
 * Колонки вкладки "Список клиентов на старт", которые скрипт ожидает найти
 * по заголовку в первой строке (регистр и порядок не важны): client,
 * last_report_link, last_updated.
 *
 * Колонки вкладки "Правки" (те же требования к заголовку): клиент, месяц,
 * статус, когда применено, ошибка.
 */
function doPost(e) {
  var result = { ok: false };
  try {
    var body = JSON.parse(e.postData.contents);
    var expectedSecret = PropertiesService.getScriptProperties().getProperty('SHARED_SECRET');

    if (!expectedSecret || body.secret !== expectedSecret) {
      result.error = 'bad secret';
      return jsonResponse_(result);
    }

    if (body.action === 'edit_status') {
      return jsonResponse_(handleEditStatus_(body));
    }
    return jsonResponse_(handleReportLink_(body));
  } catch (err) {
    result.error = String(err);
    return jsonResponse_(result);
  }
}

function handleReportLink_(body) {
  var result = { ok: false };
  if (!body.client || !body.link) {
    result.error = 'missing client or link';
    return result;
  }

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Список клиентов на старт');
  if (!sheet) {
    result.error = 'sheet tab not found';
    return result;
  }

  var data = sheet.getDataRange().getValues();
  var headers = data[0].map(function (h) {
    var v = String(h).trim().toLowerCase();
    if (v === 'клиент' || v === 'клиент:') return 'client';
    return v;
  });
  var clientCol = headers.indexOf('client');
  var linkCol = headers.indexOf('last_report_link');
  var updatedCol = headers.indexOf('last_updated');

  if (clientCol === -1 || linkCol === -1 || updatedCol === -1) {
    result.error = 'missing required column (client / last_report_link / last_updated)';
    return result;
  }

  var rowIndex = findRowByClient_(data, clientCol, body.client);
  if (rowIndex === -1) {
    result.error = 'client row not found: ' + body.client;
    return result;
  }

  sheet.getRange(rowIndex + 1, linkCol + 1).setValue(body.link);
  sheet.getRange(rowIndex + 1, updatedCol + 1).setValue(new Date());

  result.ok = true;
  return result;
}

function handleEditStatus_(body) {
  var result = { ok: false };
  if (!body.client || !body.period || !body.status) {
    result.error = 'missing client, period or status';
    return result;
  }

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Правки');
  if (!sheet) {
    result.error = 'edits sheet tab not found';
    return result;
  }

  var data = sheet.getDataRange().getValues();
  var headers = data[0].map(function (h) { return String(h).trim().toLowerCase(); });
  var clientCol = headers.indexOf('клиент');
  var periodCol = headers.indexOf('месяц');
  var statusCol = headers.indexOf('статус');
  var updatedCol = headers.indexOf('когда применено');
  var errorCol = headers.indexOf('ошибка');

  if (clientCol === -1 || periodCol === -1 || statusCol === -1 || updatedCol === -1 || errorCol === -1) {
    result.error = 'missing required column in Правки (клиент / месяц / статус / когда применено / ошибка)';
    return result;
  }

  var rowIndex = -1;
  for (var i = 1; i < data.length; i++) {
    if (String(data[i][clientCol]).trim() === String(body.client).trim()
        && String(data[i][periodCol]).trim() === String(body.period).trim()
        && !String(data[i][statusCol]).trim()) {
      rowIndex = i;
      break;
    }
  }
  if (rowIndex === -1) {
    result.error = 'pending edit row not found for: ' + body.client + ' / ' + body.period;
    return result;
  }

  sheet.getRange(rowIndex + 1, statusCol + 1).setValue(body.status);
  sheet.getRange(rowIndex + 1, updatedCol + 1).setValue(new Date());
  sheet.getRange(rowIndex + 1, errorCol + 1).setValue(body.error || '');

  result.ok = true;
  return result;
}

function findRowByClient_(data, clientCol, clientName) {
  for (var i = 1; i < data.length; i++) {
    if (String(data[i][clientCol]).trim() === String(clientName).trim()) {
      return i;
    }
  }
  return -1;
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
