import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = `${root}/outputs/t06-01`;
await fs.mkdir(outputDir, { recursive: true });
const match = JSON.parse(await fs.readFile(`${root}/docs/matched/xiyong_l_district/match_report.json`, "utf8"));
const items = match.items || [];

const workbook = Workbook.create();
const quote = workbook.worksheets.add("报价表");
const nonComp = workbook.worksheets.add("不可竞争项");
const fixed = workbook.worksheets.add("固定项");
const notes = workbook.worksheets.add("说明");
for (const sheet of [quote, nonComp, fixed, notes]) {
  sheet.showGridLines = false;
  sheet.getRange("A1:Z200").format.font = { name: "Arial", size: 10, color: "#1F2937" };
}

const headers = ["Item ID", "项目名称", "单位", "工程量 q0", "最高限价", "估算单项成本 c_i", "投标单价", "投标合价", "成本合价", "单项毛利", "毛利率", "r_eff", "层归属", "状态", "说明"];
quote.getRange("A1:O1").values = [["报价表", null, null, null, null, null, null, null, null, null, null, null, null, null, null]];
quote.getRange("A2:O2").values = [["项目：西永 L 分区公立学校（暂定名）一期工程等项目配电工程", null, null, null, null, null, null, null, null, null, null, null, null, null, null]];
quote.mergeCells("A1:O1");
quote.mergeCells("A2:O2");
quote.getRange("A4:B7").values = [
  ["合计投标价", null],
  ["合计成本", null],
  ["合计毛利", null],
  ["报价状态", "待填投标单价 / 待 Phase 1 求解结果"],
];
quote.getRange("B4").formulas = [["=SUM(H11:H92)"]];
quote.getRange("B5").formulas = [["=SUM(I11:I92)"]];
quote.getRange("B6").formulas = [["=SUM(J11:J92)"]];
quote.getRange("A10:O10").values = [headers];

const rows = items.map((item, idx) => {
  const row = 11 + idx;
  const status = item.pass_through ? "NON_COMPETITIVE" : (item.c_i == null ? "COST_REQUIRED" : "READY_FOR_SOLVE");
  const reason = item.c_i == null ? "缺少 c_i，不生成利润结论" : (item.pass_through ? "不可竞争项，单独展示" : "投标单价待 Phase 1/2 解输出");
  return [item.item_id || "", item.item_name || "", item.unit || "", item.q0 ?? null, item.cap ?? null, item.c_i ?? null, null, null, null, null, null, null, null, status, reason];
});
quote.getRange(`A11:O${10 + rows.length}`).values = rows;
for (let idx = 0; idx < rows.length; idx++) {
  const row = 11 + idx;
  quote.getRange(`H${row}`).formulas = [[`=IF(G${row}="","",D${row}*G${row})`]];
  quote.getRange(`I${row}`).formulas = [[`=IF(F${row}="","",D${row}*F${row})`]];
  quote.getRange(`J${row}`).formulas = [[`=IF(OR(G${row}="",F${row}=""),"",G${row}-F${row})`]];
  quote.getRange(`K${row}`).formulas = [[`=IF(OR(G${row}="",G${row}=0,F${row}=""),"",J${row}/G${row})`]];
}
quote.tables.add(`A10:O${10 + rows.length}`, true, "QuoteTable");
quote.freezePanes.freezeRows(10);

function writeSeparateSheet(sheet, title, subset, note) {
  sheet.getRange("A1:H1").values = [[title, null, null, null, null, null, null, null]];
  sheet.getRange("A2:H2").values = [[note, null, null, null, null, null, null, null]];
  sheet.mergeCells("A1:H1");
  sheet.mergeCells("A2:H2");
  sheet.getRange("A4:H4").values = [["Item ID", "项目名称", "单位", "工程量 q0", "最高限价", "估算单项成本 c_i", "状态", "说明"]];
  const data = subset.map((item) => [item.item_id || "", item.item_name || "", item.unit || "", item.q0 ?? null, item.cap ?? null, item.c_i ?? null, item.pass_through ? "NON_COMPETITIVE" : "FIXED_PENDING_CLASSIFICATION", item.pass_through ? "按项目分类表保留原样" : "尚未生成求解报价，不代填"]);
  if (data.length) sheet.getRange(`A5:H${4 + data.length}`).values = data;
  else sheet.getRange("A5:H5").values = [["", "当前没有已分类条目", "", null, null, null, "INFO", "不把未知项伪装成固定项"]];
  sheet.tables.add(`A4:H${Math.max(5, 4 + data.length)}`, true, `${title.replace(/[^A-Za-z0-9]/g, "")}Table`);
  sheet.freezePanes.freezeRows(4);
}
writeSeparateSheet(nonComp, "不可竞争项", items.filter((x) => x.pass_through), "来源：project_classification_table；不可竞争项与报价优化项分区展示。");
writeSeparateSheet(fixed, "固定项", items.filter((x) => !x.pass_through && x.c_i == null), "当前项目没有足够证据把未知项认定为固定项；缺失成本项单独列出，等待补证。");

notes.getRange("A1:D1").values = [["说明", null, null, null]];
notes.mergeCells("A1:D1");
notes.getRange("A3:B10").values = [
  ["字段", "口径"],
  ["投标单价", "黄色单元格为人工/求解结果输入；本工作簿不代填报价"],
  ["r_eff / 层归属", "待 Phase 1/2 求解输出后回填，当前留空不伪造结论"],
  ["估算单项成本 c_i", "来自成本清单；缺失时状态为 COST_REQUIRED"],
  ["不可竞争项", "仅按 project_classification_table 已明确的 pass_through 项进入该页"],
  ["固定项", "未知分类不自动归入固定项，避免把缺证据当作固定项"],
  ["公式", "合价、成本合价、毛利、毛利率均由报价表公式计算"],
  ["来源文件", "docs/matched/xiyong_l_district/match_report.json；config/project_classification_table.json"],
];

const headerFormat = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
quote.getRange("A1:O1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };
quote.getRange("A2:O2").format = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };
quote.getRange("A10:O10").format = headerFormat;
quote.getRange("A4:A7").format.font = { bold: true, color: "#1F2937" };
quote.getRange("G11:G92").format.fill = "#FFF2CC";
quote.getRange("H11:J92").format.numberFormat = "#,##0.00";
quote.getRange("D11:F92").format.numberFormat = "#,##0.00";
quote.getRange("K11:K92").format.numberFormat = "0.0%";
quote.getRange("A10:O92").format.borders = { insideHorizontal: { style: "thin", color: "#D9E2F3" }, bottom: { style: "thin", color: "#D9E2F3" } };
quote.getRange("A1:O92").format.wrapText = true;
quote.getRange("A:O").format.autofitColumns();
quote.getRange("A:A").format.columnWidth = 16;
quote.getRange("B:B").format.columnWidth = 28;
quote.getRange("O:O").format.columnWidth = 28;

for (const sheet of [nonComp, fixed]) {
  sheet.getRange("A1:H1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };
  sheet.getRange("A2:H2").format = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };
  sheet.getRange("A4:H4").format = headerFormat;
  sheet.getRange("D5:F100").format.numberFormat = "#,##0.00";
  sheet.getRange("A:H").format.autofitColumns();
  sheet.getRange("B:B").format.columnWidth = 28;
  sheet.getRange("H:H").format.columnWidth = 30;
}
notes.getRange("A1:D1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };
notes.getRange("A3:B3").format = headerFormat;
notes.getRange("A3:B10").format.wrapText = true;
notes.getRange("A:A").format.columnWidth = 20;
notes.getRange("B:B").format.columnWidth = 85;

const inspect = await workbook.inspect({ kind: "table", sheetId: "报价表", range: "A1:O18", include: "values,formulas", tableMaxRows: 18, tableMaxCols: 15, maxChars: 12000 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "报价表", range: "A1:O18", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/报价表预览.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/报价表.xlsx`);
console.log(`SAVED:${outputDir}/报价表.xlsx`);
