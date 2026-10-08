/** Portal 卡片字段字典（2026-10-08 配置化方案）
 *
 * 全站字段定义一处管理。加新字段？加一行。
 * 用户在设置页勾选"卡片显示哪些字段"，存的是 key 数组。
 */
export interface FieldDef {
  label: string;
  type: 'text' | 'money' | 'percent' | 'badge' | 'date';
}

export const FIELD_DICT: Record<string, FieldDef> = {
  // 项目
  name:          { label: '名称',   type: 'text' },
  stage:         { label: '阶段',   type: 'badge' },
  bid_amount:    { label: '中标金额', type: 'money' },
  limit_total:   { label: '限价',   type: 'money' },
  progress:      { label: '进度',   type: 'percent' },
  // 项目摘要（2026-10-08 展开卡片）
  contract_amount: { label: '合同金额', type: 'money' },
  start_date:      { label: '开工时间', type: 'date' },
  exec_cost:       { label: '实施成本', type: 'money' },
  profit_margin:   { label: '利润率',   type: 'percent' },
  // 单位明细（2026-10-08 展开卡片详情）
  paid:         { label: '已付款',   type: 'money' },
  unpaid:       { label: '未付款',   type: 'money' },
  pay_nodes:    { label: '付款节点', type: 'text' },
  suppliers:    { label: '供应商',   type: 'text' },
  labor_units:  { label: '劳务单位', type: 'text' },
  // 单位
  role:          { label: '角色',   type: 'badge' },
  project_count: { label: '项目数', type: 'text' },
  total_amount:  { label: '累计金额', type: 'money' },
  total_paid:    { label: '已付',   type: 'money' },
  total_payable: { label: '应付',   type: 'money' },
  // 通用
  title:         { label: '标题',   type: 'text' },
  desc:          { label: '描述',   type: 'text' },
  text:          { label: '内容',   type: 'text' },
  done:          { label: '完成',   type: 'badge' },
  status:        { label: '状态',   type: 'badge' },
  date:          { label: '日期',   type: 'date' },
  amount:        { label: '金额',   type: 'money' },
} as const;

export type FieldKey = keyof typeof FIELD_DICT;
