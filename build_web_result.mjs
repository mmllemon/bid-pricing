import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const input = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const output = process.argv[3];
const workbook = Workbook.create();
const quote = workbook.worksheets.add("报价表");
const summary = workbook.worksheets.add("汇总");
const notes = workbook.worksheets.add("规则与说明");
const sources = workbook.worksheets.add("数据来源");
for (const sheet of [quote, summary, notes, sources]) {
  sheet.showGridLines = false;
  sheet.getRange("A1:Z300").format.font = { name: "Arial", size: 10, color: "#1F2937" };
}
const header = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
const items = input.items || [];
const columns = ["Item ID", "项目名称", "单位", "工程量 q0", "结算量 q1", "最高限价", "成本 c_i", "最优综合单价", "报价比率", "报价合价", "成本合价", "结算收入", "单项毛利", "毛利率", "状态", "说明"];
quote.getRange("A1:P1").values = [["分部分项最优报价表（结算调整版）", ...Array(15).fill(null)]];
quote.mergeCells("A1:P1");
quote.getRange("A2:P2").values = [[`项目：${input.project_id || "当前项目"}｜目标总报价：${Number(input.target_total).toFixed(2)} 元｜报价比率区间：${(Number(input.ratio_min ?? 0.5) * 100).toFixed(0)}%～${(Number(input.ratio_max ?? 1) * 100).toFixed(0)}%｜C13：最高限价基准 ±50%，结算调整`, ...Array(15).fill(null)]];
quote.mergeCells("A2:P2");
const resultSummary = input.summary || {};
const costTotal = resultSummary.cost_total ?? items.reduce((s, i) => s + Number(i["成本合价"] || 0), 0);
const marginTotal = resultSummary.margin_total ?? input.objective;
const lossCount = resultSummary.loss_item_count ?? items.filter(i => Number(i["单项毛利"] || 0) < 0).length;
quote.getRange("A4:B10").values = [["目标总报价", input.target_total], ["可竞争预算", input.competitive_budget], ["固定税前项", input.fixed_pretax ?? 0], ["增值税", null], ["附加税", null], ["重算总价", null], ["总价残差", null]];
quote.getRange("B7").formulas = [[`=ROUND((B5+B6)*${Number(input.vat_rate ?? 0.09)},2)`]];
quote.getRange("B8").formulas = [[`=ROUND(B7*${Number(input.surtax_rate ?? 0.12)},2)`]];
quote.getRange("B9").formulas = [["=ROUND(B5+B6+B7+B8,2)"]];
quote.getRange("B10").formulas = [["=B9-B4"]];
quote.getRange("D4:E10").values = [["求解状态", input.solver_status || "OPTIMAL"], ["优化分项数量", input.item_count ?? items.length], ["成本合计", costTotal], ["预计毛利", marginTotal], ["亏损项数量", lossCount], ["人工报价项", input.manual_item_count ?? 0], ["C13条款", "已纳入结算调整 MILP"]];
quote.getRange("A12:P12").values = [columns];
const rows = items.map((item) => [item["项目编码"], item["项目名称"], item["单位"] || "", item["工程量"], item["成本工程量"], item["最高限价"], item["含税成本单价"], item["最优报价单价"], null, null, null, item["结算收入"], null, null, item["报价状态"] === "MANUAL_REVIEW" ? "MANUAL_REVIEW" : (item["单项毛利"] ?? 0) < 0 || (item["报价比率"] ?? 1) < 0.5 ? "LOSS_REVIEW" : "PASS", item["说明"] || ((item["单项毛利"] ?? 0) < 0 ? "单项毛利为负，需人工复核" : "目标函数与约束复验通过")]);
const start = 13;
if (rows.length) {
  const end = start + rows.length - 1;
  quote.getRange(`A${start}:P${end}`).values = rows;
  for (let r = start; r <= end; r++) {
    if (rows[r - start][13] === "MANUAL_REVIEW") {
      const hasCost = rows[r - start][4] != null && rows[r - start][6] != null;
      quote.getRange(`I${r}:N${r}`).formulas = [[`=""`, `=""`, hasCost ? `=E${r}*G${r}` : `=""`, `=""`, `=""`, `=""`]];
    } else {
      quote.getRange(`I${r}`).formulas = [[`=IF(F${r}=0,"",H${r}/F${r})`]];
      quote.getRange(`J${r}`).formulas = [[`=D${r}*H${r}`]];
      quote.getRange(`K${r}`).formulas = [[`=E${r}*G${r}`]];
      quote.getRange(`M${r}`).formulas = [[`=L${r}-K${r}`]];
      quote.getRange(`N${r}`).formulas = [[`=IF(L${r}=0,"",M${r}/L${r})`]];
    }
  }
  quote.tables.add(`A12:P${end}`, true, "WebQuoteResult");
  quote.freezePanes.freezeRows(12);
  quote.getRange(`D${start}:M${end}`).format.numberFormat = "#,##0.00";
  quote.getRange(`I${start}:I${end}`).format.numberFormat = "0.0%";
  quote.getRange(`N${start}:N${end}`).format.numberFormat = "0.0%";
  quote.getRange(`A12:P${end}`).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2F3" }, bottom: { style: "thin", color: "#D9E2F3" } };
  quote.getRange(`I${start}:I${end}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0.5, format: { fill: "#FFF2CC", font: { color: "#9C6500", bold: true } } });
  quote.getRange(`M${start}:M${end}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { fill: "#FCE4D6", font: { color: "#9C0006", bold: true } } });
  quote.getRange("A:A").format.columnWidth = 16; quote.getRange("B:B").format.columnWidth = 30; quote.getRange("C:C").format.columnWidth = 10;
  quote.getRange("D:N").format.columnWidth = 14; quote.getRange("O:O").format.columnWidth = 14; quote.getRange("P:P").format.columnWidth = 32;
}
quote.getRange("A1:P1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };
quote.getRange("A2:P2").format = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };
quote.getRange("A12:P12").format = header;
quote.getRange("A4:A10").format.font = { bold: true }; quote.getRange("D4:D10").format.font = { bold: true };
quote.getRange("B4:B10").format.numberFormat = "#,##0.00"; quote.getRange("E4:E10").format.numberFormat = "#,##0.00";

summary.getRange("A1:F1").values = [["报价汇总", ...Array(5).fill(null)]]; summary.mergeCells("A1:F1");
summary.getRange("A3:B10").values = [["指标", "数值"], ["目标总报价", input.target_total], ["重算总价", null], ["总价残差", null], ["可竞争预算", input.competitive_budget], ["固定税前项", input.fixed_pretax ?? 0], ["预计毛利", marginTotal], ["亏损项数量", lossCount]];
summary.getRange("B5").formulas = [["='报价表'!B9"]]; summary.getRange("B6").formulas = [["='报价表'!B10"]]; summary.getRange("A3:B3").format = header;
summary.getRange("A3:A10").format.font = { bold: true }; summary.getRange("B4:B10").format.numberFormat = "#,##0.00"; summary.getRange("A1:F1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } }; summary.getRange("A:A").format.columnWidth = 24; summary.getRange("B:B").format.columnWidth = 20;

notes.getRange("A1:C1").values = [["规则与说明", null, null]]; notes.mergeCells("A1:C1");
notes.getRange("A3:B13").values = [["项目", "说明"], ["成本政策", "分部分项单价可以低于成本；成本仅参与利润目标函数，允许单项亏损。"], ["固定项", `措施项目费与规费按当前固定税前金额 ${Number(input.fixed_pretax ?? 0).toFixed(2)} 元处理。`], ["税费", `增值税率 ${(Number(input.vat_rate ?? 0.09) * 100).toFixed(2)}%，附加税率 ${(Number(input.surtax_rate ?? 0.12) * 100).toFixed(2)}%。`], ["不平衡条款", "最高限价为基准，±50%触发结算调整；工程量±15%以内按投标价，超出部分按结算调整公式处理。"], ["亏损项", `本次共有 ${lossCount} 项单项毛利为负，需人工复核。`], ["缺失项", "限价或成本任一清单缺少对应项、最高限价或成本锚点时，不纳入 C13 优化，须人工报价或补充资料。"], ["报价比率", `报价比率 = 单项报价 ÷ 单项最高限价；本次区间 ${(Number(input.ratio_min ?? 0.5) * 100).toFixed(0)}%～${(Number(input.ratio_max ?? 1) * 100).toFixed(0)}%。`], ["低价确认", input.low_ratio_review_required ? "存在低于50%的报价比率，已标记为需人工确认；是否废标须以招标文件约定为准。" : "本次没有低于50%的报价比率。"], ["结果状态", `求解 ${input.solver_status || "OPTIMAL"}；利润已按结算调整版收入函数独立复算。`], ["维护", "如目标总报价或项目政策变化，应重新运行主流程，不直接修改结果列。"]];
notes.getRange("A3:B3").format = header;
notes.getRange("A3:A7").format.font = { bold: true }; notes.getRange("A:A").format.columnWidth = 18; notes.getRange("B:B").format.columnWidth = 75; notes.getRange("A1:C1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };

sources.getRange("A1:C1").values = [["数据来源", null, null]]; sources.mergeCells("A1:C1");
sources.getRange("A3:C7").values = [["来源类型", "来源内容", "说明"], ["限价清单", "用户上传 Excel", "综合单价列作为不含税最高限价"], ["成本清单", "用户上传 Excel", "综合单价列作为含税成本单价"], ["优化模型", "Phase 2 Settlement MILP", "C13 结算调整规则"], ["计算规则", "项目报价政策配置", "最高限价基准 ±50%，工程量偏差 15%"]];
sources.getRange("A3:C3").format = header; sources.getRange("A:A").format.columnWidth = 18; sources.getRange("B:B").format.columnWidth = 30; sources.getRange("C:C").format.columnWidth = 55; sources.getRange("A1:C1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F2937" } };

const blob = await SpreadsheetFile.exportXlsx(workbook);
await blob.save(output);
