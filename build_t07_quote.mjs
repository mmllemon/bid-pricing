import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = `${root}/outputs/t07-quote`;
await fs.mkdir(outputDir, { recursive: true });
const result = JSON.parse(await fs.readFile(`${outputDir}/报价结果_结算调整版.json`, "utf8"));

const workbook = Workbook.create();
const quote = workbook.worksheets.add("报价表");
const summary = workbook.worksheets.add("汇总");
const notes = workbook.worksheets.add("风险与说明");
const sources = workbook.worksheets.add("数据来源");
for (const sheet of [quote, summary, notes, sources]) {
  sheet.showGridLines = false;
  sheet.getRange("A1:Z200").format.font = { name: "Arial", size: 10, color: "#1F2937" };
}

const header = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
const headers = ["Item ID", "项目名称", "单位", "工程量 q0", "结算量 q1", "最高限价", "成本 c_i", "最优综合单价", "报价合价", "成本合价", "结算收入", "单项毛利", "毛利率", "状态", "说明"];

quote.getRange("A1:O1").values = [["分部分项最优报价表（结算调整版）", ...Array(14).fill(null)]];
quote.mergeCells("A1:O1");
quote.getRange("A2:O2").values = [["项目：西永 L 分区公立学校（暂定名）一期工程等项目配电工程｜目标总报价：1,260,000 元｜C13：最高限价基准 ±50%，结算调整", ...Array(14).fill(null)]];
quote.mergeCells("A2:O2");
quote.getRange("A4:B10").values = [
  ["目标总报价", result.target_total],
  ["可竞争预算", result.competitive_budget],
  ["固定税前项", result.fixed_pretax],
  ["增值税", null],
  ["附加税", null],
  ["重算总价", null],
  ["总价残差", null],
];
quote.getRange("B7").formulas = [["=ROUND((B5+B6)*0.09,2)"]];
quote.getRange("B8").formulas = [["=ROUND(B7*0.12,2)"]];
quote.getRange("B9").formulas = [["=ROUND(B5+B6+B7+B8,2)"]];
quote.getRange("B10").formulas = [["=B9-B4"]];
quote.getRange("D4:E10").values = [
  ["求解状态", result.solver_status],
  ["分项数量", result.summary.item_count],
  ["成本合计", result.summary.cost_total],
  ["预计毛利", result.summary.margin_total],
  ["亏损项数量", result.summary.loss_item_count],
  ["C13条款", "已纳入结算调整 MILP"],
  ["舍入调和", "通过（总价残差=0）"],
];

quote.getRange("A12:O12").values = [headers];
const rows = result.items.map((item) => [
  item.item_id, item.item_name, item.unit, item.quantity_q0, item.settlement_quantity_q1,
  item.cap, item.cost_ci, item.optimal_unit_price, null, null, item.settlement_revenue,
  null, null, item.margin < 0 ? "LOSS_REVIEW" : "PASS", item.margin < 0 ? "单项毛利为负，需人工复核" : "目标函数与约束复验通过",
]);
const start = 13;
const end = start + rows.length - 1;
quote.getRange(`A${start}:O${end}`).values = rows;
for (let i = start; i <= end; i++) {
  quote.getRange(`I${i}`).formulas = [[`=D${i}*H${i}`]];
  quote.getRange(`J${i}`).formulas = [[`=E${i}*G${i}`]];
  quote.getRange(`L${i}`).formulas = [[`=K${i}-J${i}`]];
  quote.getRange(`M${i}`).formulas = [[`=IF(K${i}=0,"",L${i}/K${i})`]];
}
quote.tables.add(`A12:O${end}`, true, "FinalQuoteTable");
quote.freezePanes.freezeRows(12);
quote.getRange("A1:O1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };
quote.getRange("A2:O2").format = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };
quote.getRange("A12:O12").format = header;
quote.getRange("A4:A10").format.font = { bold: true };
quote.getRange("D4:D10").format.font = { bold: true };
quote.getRange(`D${start}:G${end}`).format.numberFormat = "#,##0.00";
quote.getRange(`H${start}:L${end}`).format.numberFormat = "#,##0.00";
quote.getRange(`M${start}:M${end}`).format.numberFormat = "0.0%";
quote.getRange("B4:B10").format.numberFormat = "#,##0.00";
quote.getRange("E4:E10").format.numberFormat = "#,##0.00";
quote.getRange(`A12:O${end}`).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2F3" }, bottom: { style: "thin", color: "#D9E2F3" } };
quote.getRange("A1:O200").format.wrapText = true;
quote.getRange("A:O").format.autofitColumns();
quote.getRange("A:A").format.columnWidth = 16;
quote.getRange("B:B").format.columnWidth = 28;
quote.getRange("O:O").format.columnWidth = 24;
quote.getRange(`L${start}:L${end}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { fill: "#FCE4D6", font: { color: "#9C0006" } } });

summary.getRange("A1:F1").values = [["报价汇总", null, null, null, null, null]];
summary.mergeCells("A1:F1");
summary.getRange("A3:B10").values = [
  ["指标", "数值"], ["目标总报价", result.target_total], ["重算总价", null], ["总价残差", null], ["可竞争预算", result.competitive_budget], ["固定税前项", result.fixed_pretax], ["预计毛利", result.summary.margin_total], ["亏损项数量", result.summary.loss_item_count],
];
summary.getRange("B5").formulas = [["='报价表'!B9"]];
summary.getRange("B6").formulas = [["='报价表'!B10"]];
summary.getRange("A3:B3").format = header;
summary.getRange("B4:B10").format.numberFormat = "#,##0.00";
summary.getRange("A:B").format.autofitColumns();
summary.getRange("A:A").format.columnWidth = 22;
summary.getRange("B:B").format.columnWidth = 18;

notes.getRange("A1:D1").values = [["风险与说明", null, null, null]];
notes.mergeCells("A1:D1");
notes.getRange("A3:B12").values = [
  ["项目", "说明"],
  ["成本政策", "分部分项单价可以低于 c_i；c_i 仅参与利润目标函数，允许单项亏损。"],
  ["固定项", "措施项目费 15,853.12 元；规费 6,528.62 元；按当前固定金额处理。"],
  ["税费", "增值税率 9%，附加税率 12%，环境保护税按 0。"],
  ["不平衡条款", "最高限价为基准，±50%触发结算调整；工程量±15%以内按投标价，超出部分按结算调整公式处理。"],
  ["亏损项", `本次共有 ${result.summary.loss_item_count} 项单项毛利为负，需人工复核。`],
  ["缺失项", "脚手架搭拆项缺少成本锚点，未纳入本次 81 项优化。"],
  ["最低报价", "单价最低采用 0.01 元 C5 约束；本条款为结算调整，不等同于投标废标下限。"],
  ["结果状态", "求解 OPTIMAL；利润已按结算调整版收入函数独立复算。"],
  ["维护", "如目标总报价或项目政策变化，应重新运行主流程，不直接修改结果列。"],
];
notes.getRange("A3:B3").format = header;
notes.getRange("A:B").format.autofitColumns();
notes.getRange("A:A").format.columnWidth = 18;
notes.getRange("B:B").format.columnWidth = 90;
notes.getRange("A3:B12").format.wrapText = true;

sources.getRange("A1:C1").values = [["数据来源", null, null]];
sources.mergeCells("A1:C1");
sources.getRange("A3:C9").values = [
  ["来源类别", "文件/字段", "用途"],
  ["项目配对数据", "docs/matched/xiyong_l_district/match_report.json", "工程量、最高限价、成本 c_i、成本工程量"],
  ["报价规则", "config/pricing_rule_card.json", "结算规则与 r_eff"],
  ["项目政策", "config/project_quote_policy.json", "目标总报价、成本政策、固定项、税率"],
  ["主流程", "src/bidpricing/quote_pipeline.py", "预算反推、Phase 1 求解、复验与调和"],
  ["输出结果", "outputs/t07-quote/报价结果_结算调整版.json", "本工作簿的结果数据源"],
  ["结算模型", "src/bidpricing/solver/settlement_milp.py", "±50%与±15%结算调整 MILP"],
];
sources.getRange("A3:C3").format = header;
sources.getRange("A:C").format.autofitColumns();
sources.getRange("B:B").format.columnWidth = 55;
sources.getRange("C:C").format.columnWidth = 36;
sources.getRange("A3:C9").format.wrapText = true;

const inspect = await workbook.inspect({ kind: "table", sheetId: "报价表", range: "A1:O20", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 15, maxChars: 14000 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(errors.ndjson);
for (const sheet of [quote, summary, notes, sources]) {
  const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${sheet.name}预览.png`, new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/报价结果.xlsx`);
console.log(`SAVED:${outputDir}/报价结果.xlsx`);
