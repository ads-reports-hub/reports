/**
 * Эталонная копия скрипта, который реально живёт внутри гугл-таблицы
 * "Список клиентов на старт" (Extensions -> Apps Script).
 *
 * Принимает POST от GitHub Actions после генерации отчёта и дописывает
 * ссылку + время в строку нужного клиента. Секрет хранится в Script
 * Properties (Project Settings -> Script Properties), НЕ в самом коде,
 * чтобы он не был виден даже тем, у кого есть доступ на просмотр скрипта.
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
 * Колонки таблицы, которые скрипт ожидает найти по заголовку в первой
 * строке (регистр и порядок не важны): client, last_report_link, last_updated.
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
    if (!body.client || !body.link) {
      result.error = 'missing client or link';
      return jsonResponse_(result);
    }

    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Список клиентов на старт');
    if (!sheet) {
      result.error = 'sheet tab not found';
      return jsonResponse_(result);
    }

    var data = sheet.getDataRange().getValues();
    var headers = data[0].map(function (h) { return String(h).trim().toLowerCase(); });
    var clientCol = headers.indexOf('client');
    var linkCol = headers.indexOf('last_report_link');
    var updatedCol = headers.indexOf('last_updated');

    if (clientCol === -1 || linkCol === -1 || updatedCol === -1) {
      result.error = 'missing required column (client / last_report_link / last_updated)';
      return jsonResponse_(result);
    }

    var rowIndex = -1;
    for (var i = 1; i < data.length; i++) {
      if (String(data[i][clientCol]).trim() === String(body.client).trim()) {
        rowIndex = i;
        break;
      }
    }
    if (rowIndex === -1) {
      result.error = 'client row not found: ' + body.client;
      return jsonResponse_(result);
    }

    sheet.getRange(rowIndex + 1, linkCol + 1).setValue(body.link);
    sheet.getRange(rowIndex + 1, updatedCol + 1).setValue(new Date());

    result.ok = true;
    return jsonResponse_(result);
  } catch (err) {
    result.error = String(err);
    return jsonResponse_(result);
  }
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
