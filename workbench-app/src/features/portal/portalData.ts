/**
 * 工程智算 · 全景大盘数据模型（P1 前端整合：由 frontend/js/portal-data.js 迁入 React）
 *
 * 迁移说明：数据字面量与 getter 逻辑逐字保留（脚本机械转换），仅把 IIFE + global.PORTAL_DATA
 * 改为 ES module 导出。原文件保留在 frontend/ 直到 P4 删除。
 */

export interface PortalBranch {
  id: string;
  code: string;
  label: string;
  subtitle?: string;
  isDefault?: boolean;
}

export interface PortalModule {
  id: string;
  code: string;
  name: string;
  subtitle: string;
  group: string;
  angle: number;
  color: string;
  tagColor?: string;
  icon: string;
  branches: PortalBranch[];
  data: Record<string, PortalItem[]>;
}

/** 三级数据实体：字段随业务域不同而异，故留开放形状。 */
export interface PortalItem {
  id: string;
  code: string;
  title: string;
  desc?: string;
  stage?: string;
  progress?: number;
  limitAmount?: string;
  bidAmount?: string;
  costBudget?: string;
  metrics?: [string, string][];
  profile?: Record<string, string>;
  quote?: Record<string, string>;
  execution?: Record<string, string>;
  docs?: { name: string; size: string; time: string }[];
  todos?: { id: string; text: string; done: boolean }[];
  planDetail?: Record<string, string | number>;
  costDetail?: Record<string, string>;
  finDetail?: Record<string, string>;
  taskDetail?: Record<string, string>;
  msDetail?: Record<string, string>;
  [k: string]: unknown;
}

export const MODULES: PortalModule[] = [
    // ===== 1. 项目经营 (M-01) =====
    {
      id: 'biz',
      code: 'M-01',
      name: '项目经营',
      subtitle: '项目库与经营全景',
      group: 'operations',
      angle: 40,
      color: '#06b6d4',
      tagColor: '#06b6d4',
      icon: 'B',
      branches: [
        { id: 'projects', code: 'B-1', label: '工程项目库', subtitle: '在投标与在建工程台账', isDefault: true },
        { id: 'overview', code: 'B-2', label: '经营总览', subtitle: '毛利与现金流大盘' }
      ],
      data: {
        projects: [
          {
            id: 'proj-xiyong',
            code: 'P-01',
            title: '西永L公立学校项目',
            stage: '投标',
            limitAmount: '1,500,000.00',
            bidAmount: '1,450,000.00',
            costBudget: '1,280,000.00',
            desc: '九年一贯制公立学校新建工程，含综合教学楼、风雨操场及室外配套工程。',
            progress: 35,
            profile: {
              contractNo: 'XY-2026-EDU-09',
              client: '西永微电子产业园区建设局',
              builder: '中建八局西南分公司',
              openDate: '2026-09-21',
              scale: '建筑面积 24,000㎡ / 48个教学班'
            },
            quote: {
              targetTotal: '1,450,000.00',
              rate: '-3.33%',
              vatRate: '9%',
              surtaxRate: '12%',
              fixedPretax: '120,000.00',
              guardrail: '50% ~ 80%'
            },
            execution: {
              status: '标书编制完成，正在进行最终不平衡单价调优',
              team: '造价一所 - 李工（负责人）、陈工（安装）',
              riskLevel: '低风险（合规得分 98.5）'
            },
            docs: [
              { name: '西永L学校招标文件.pdf', size: '14.2 MB', time: '2026-09-19' },
              { name: '工程量清单最高限价表.xlsx', size: '3.8 MB', time: '2026-09-20' },
              { name: '投标报价优化推演方案A.json', size: '256 KB', time: '2026-09-22' }
            ],
            todos: [
              { id: 't-xy-1', text: '复核招标答疑澄清函中措施费变更', done: true },
              { id: 't-xy-2', text: '与项目经理核对现场临建与配电报价', done: false },
              { id: 't-xy-3', text: '完成电子标书封标与CA证书加锁', done: false }
            ]
          },
          {
            id: 'proj-jinrong',
            code: 'P-02',
            title: '金融城5号配电工程',
            stage: '中标在建',
            limitAmount: '22,000,000.00',
            bidAmount: '20,800,000.00',
            costBudget: '17,600,000.00',
            desc: '江北嘴金融城超高层建筑配电房、高低压成套开关柜及干式变压器供货安装。',
            progress: 68,
            profile: {
              contractNo: 'JRC-2024-POW-05',
              client: '金融城投资开发集团',
              builder: '华电工程电力分公司',
              openDate: '2024-05-20',
              scale: '变压器容量 4×2500kVA / 柴油发电机组 1600kW'
            },
            quote: {
              targetTotal: '20,800,000.00',
              rate: '-5.45%',
              vatRate: '13%',
              surtaxRate: '12%',
              fixedPretax: '1,500,000.00',
              guardrail: '60% ~ 85%'
            },
            execution: {
              status: '主体配电房设备就位，正在进行母线槽敷设与耐压试验',
              team: '电力项目部 - 张总工、王工',
              riskLevel: '中风险（部分进口断路器到货周期延长）'
            },
            docs: [
              { name: '配电工程主施工合同.pdf', size: '28.5 MB', time: '2024-06-10' },
              { name: '变压器进场验收及试验报告.pdf', size: '8.4 MB', time: '2026-08-15' },
              { name: '第三期工程进度款申请表.xlsx', size: '2.1 MB', time: '2026-09-10' }
            ],
            todos: [
              { id: 't-jr-1', text: '核对母线槽变更签证工程量', done: true },
              { id: 't-jr-2', text: '上报第4期工程进度计量款申报单', done: false }
            ]
          },
          {
            id: 'proj-lvyou',
            code: 'P-03',
            title: '重启旅游学校配电项目',
            stage: '投标',
            limitAmount: '3,000,000.00',
            bidAmount: '2,850,000.00',
            costBudget: '2,420,000.00',
            desc: '职业教育实训基地双回路供电系统改造、老旧电缆更换及配电房增容。',
            progress: 20,
            profile: {
              contractNo: 'LY-2026-PWR-01',
              client: '城市旅游职业学院',
              builder: '中标候选人公示中',
              openDate: '2026-09-16',
              scale: '增容改造 1600kVA / 高压电缆敷设 2.4km'
            },
            quote: {
              targetTotal: '2,850,000.00',
              rate: '-5.00%',
              vatRate: '9%',
              surtaxRate: '12%',
              fixedPretax: '220,000.00',
              guardrail: '55% ~ 80%'
            },
            execution: {
              status: '已开标，第一中标候选人公示期，准备签约资料',
              team: '商务部 - 孙经理',
              riskLevel: '安全（开标排名第一）'
            },
            docs: [
              { name: '旅游学校招标文件及图纸.zip', size: '54.2 MB', time: '2026-09-01' },
              { name: '中标候选人公示截屏.png', size: '1.2 MB', time: '2026-09-17' }
            ],
            todos: [
              { id: 't-ly-1', text: '办理履约保函与保险材料', done: false },
              { id: 't-ly-2', text: '编制深化设计图纸与首批设备订货排期', done: false }
            ]
          },
          {
            id: 'proj-shichuan',
            code: 'P-04',
            title: '石船安置房项目',
            stage: '未中标',
            limitAmount: '12,000,000.00',
            bidAmount: '11,200,000.00',
            costBudget: '10,100,000.00',
            desc: '石船镇拆迁安置房住宅小区 1-4# 楼机电安装与智能化总承包工程。',
            progress: 100,
            profile: {
              contractNo: 'SC-2026-AZ-04',
              client: '空港新城开发建设有限公司',
              builder: '友商建工集团',
              openDate: '2026-09-25',
              scale: '总建筑面积 45,000㎡ / 住宅 380 户'
            },
            quote: {
              targetTotal: '11,200,000.00',
              rate: '-6.67%',
              vatRate: '9%',
              surtaxRate: '12%',
              fixedPretax: '800,000.00',
              guardrail: '50% ~ 75%'
            },
            execution: {
              status: '复盘归档：第一名下浮 8.2%，单价偏高 18 万未中标',
              team: '造价二所 - 周工',
              riskLevel: '归档（投标复盘已完成）'
            },
            docs: [
              { name: '石船安置房投标复盘报告.pdf', size: '2.4 MB', time: '2026-09-26' },
              { name: '开标各家报价横向对比明细.xlsx', size: '1.5 MB', time: '2026-09-26' }
            ],
            todos: [
              { id: 't-sc-1', text: '办理投标保证金 20 万元退还申请', done: true },
              { id: 't-sc-2', text: '将竞争对手报价策略归入知识库', done: true }
            ]
          }
        ],
        overview: [
          {
            id: 'ov-pipeline',
            code: 'OV-01',
            title: '在投标与在建漏斗',
            desc: '全周期项目储备总金额 3,850 万元，投标中 2 项，中标在建 1 项。',
            metrics: [['累计储备', '3,850 万'], ['在投标', '2 项'], ['中标率', '42.8%']]
          },
          {
            id: 'ov-margin',
            code: 'OV-02',
            title: '项目综合毛利水平',
            desc: '当前在建与投标项目加权平均预估毛利率为 14.6%，处于行业健康区间。',
            metrics: [['平均毛利', '14.6%'], ['最高毛利', '18.2%'], ['风险预警', '0项']]
          },
          {
            id: 'ov-cash',
            code: 'OV-03',
            title: '工程进度款回款进度',
            desc: '本年度累计工程计量进度款已到账 1,420 万元，综合到账率 91.2%。',
            metrics: [['累计回款', '1,420 万'], ['到账率', '91.2%'], ['应收账款', '140 万']]
          }
        ]
      }
    },

    // ===== 2. 投标报价 (Q-01) =====
    {
      id: 'quote',
      code: 'Q-01',
      name: '投标报价',
      subtitle: '核心优化沙盘',
      group: 'engineering',
      angle: 180,
      color: '#ff6b00',
      tagColor: '#ff6b00',
      icon: 'Q',
      branches: [
        { id: 'slots', code: 'B-1', label: '比选方案中心', subtitle: 'A/B/C 三槽位推演', isDefault: true },
        { id: 'engine', code: 'B-2', label: '核心求解引擎', subtitle: 'Phase 1/2 整数规划' }
      ],
      data: {
        slots: [
          {
            id: 'slot-base',
            code: 'S-A',
            title: '基准方案 (A · 适中稳妥)',
            type: 'scheme',
            desc: '保持合理利润空间与平衡调价，严格控制单价防线，合规安全分最高。',
            metrics: [['总报价', '1,450,000 元'], ['综合下浮', '-3.33%'], ['合规得分', '98.5分']],
            planDetail: {
              slotName: '方案 A (基准)',
              strategy: '平衡调价 · 规费税金剥离',
              targetTotal: '1,450,000.00',
              rateRange: '50% ~ 80%',
              unbalancedCount: 0,
              grossProfit: '170,000.00',
              grossMargin: '11.72%'
            }
          },
          {
            id: 'slot-agg',
            code: 'S-B',
            title: '激进方案 (B · 顶格下浮)',
            type: 'scheme',
            desc: '以低价夺标为核心导向，重点压降可优化清单项单价，逼近安全防线底线。',
            metrics: [['总报价', '1,380,000 元'], ['综合下浮', '-8.00%'], ['合规得分', '84.0分']],
            planDetail: {
              slotName: '方案 B (激进)',
              strategy: '激进下浮 · 抢标模式',
              targetTotal: '1,380,000.00',
              rateRange: '45% ~ 75%',
              unbalancedCount: 6,
              grossProfit: '100,000.00',
              grossMargin: '7.25%'
            }
          },
          {
            id: 'slot-unbal',
            code: 'S-C',
            title: '不平衡报价方案 (C · 前重后轻)',
            type: 'scheme',
            desc: '早收款分项适当调高单价加速资金回笼，后收款或预计减量项调低单价。',
            metrics: [['总报价', '1,448,000 元'], ['资金回笼', '+18.4%'], ['合规得分', '92.0分']],
            planDetail: {
              slotName: '方案 C (不平衡优化)',
              strategy: '早收款调增 · 预计增量项适度上浮',
              targetTotal: '1,448,000.00',
              rateRange: '50% ~ 85%',
              unbalancedCount: 4,
              grossProfit: '192,000.00',
              grossMargin: '13.26%'
            }
          }
        ],
        engine: [
          {
            id: 'eng-simplex',
            code: 'E-01',
            title: 'Phase 1/2 整数规划求解器',
            desc: '高精度整数规划算法，支持微秒级输出满足上百项约束的最优解单价组合。',
            metrics: [['求解耗时', '0.42ms'], ['约束项', '142条'], ['精度级别', '分角精准']]
          },
          {
            id: 'eng-guard',
            code: 'E-02',
            title: '畸形单价动态风控防线',
            desc: '实时拦截偏离最高限价过多的异常单价，彻底消除专家评审废标隐患。',
            metrics: [['防线区间', '50%~80%'], ['废标拦截', '100%'], ['修正条款', '已启用']]
          }
        ]
      }
    },

    // ===== 3. 实施成本 (C-02) =====
    {
      id: 'cost',
      code: 'C-02',
      name: '实施成本',
      subtitle: '责任基线与归集',
      group: 'engineering',
      angle: 140,
      color: '#0284c7',
      tagColor: '#0284c7',
      icon: 'C',
      branches: [
        { id: 'collection', code: 'B-1', label: '工料机动态归集', subtitle: '采购/劳务/机械发生额', isDefault: true },
        { id: 'baseline', code: 'B-2', label: '责任成本基线', subtitle: '预算红线指标' }
      ],
      data: {
        collection: [
          {
            id: 'c-mat',
            code: 'CB-01',
            title: '主材与辅助材料消耗归集',
            type: 'costItem',
            desc: '钢材、电缆、水泥等主宗物资集中采购发生额核算与进项税 13% 抵扣。',
            metrics: [['控制基线', '840,000 元'], ['已发生', '785,000 元'], ['偏差率', '-6.5%']],
            costDetail: {
              budget: '840,000.00',
              spent: '785,000.00',
              remaining: '55,000.00',
              vatDeduction: '13%',
              alertLevel: '正常安全 (绿灯)'
            }
          },
          {
            id: 'c-labor',
            code: 'CB-02',
            title: '专业劳务分包计量费用',
            type: 'costItem',
            desc: '土建班组、水电安装及电焊劳务计量支付台账，进项税 9%/3% 简易计税。',
            metrics: [['控制基线', '380,000 元'], ['已发生', '362,000 元'], ['偏差率', '-4.7%']],
            costDetail: {
              budget: '380,000.00',
              spent: '362,000.00',
              remaining: '18,000.00',
              vatDeduction: '9%',
              alertLevel: '正常安全 (绿灯)'
            }
          },
          {
            id: 'c-mech',
            code: 'CB-03',
            title: '施工机械租赁与进退场费',
            type: 'costItem',
            desc: '汽车吊、挖掘机、高空作业车台班租赁费用审核与结算凭证。',
            metrics: [['控制基线', '65,000 元'], ['已发生', '68,200 元'], ['偏差率', '+4.9%']],
            costDetail: {
              budget: '65,000.00',
              spent: '68,200.00',
              remaining: '-3,200.00',
              vatDeduction: '13%',
              alertLevel: '轻度超支预警 (黄灯)'
            }
          }
        ],
        baseline: [
          {
            id: 'c-base-lock',
            code: 'BL-01',
            title: '目标责任成本基线锁定',
            desc: '项目开工前严格锁定工料机责任成本包，严禁无预算开支。',
            metrics: [['目标利润率', '12.5%'], ['责任人', '项目经理'], ['审核状态', '已批准']]
          }
        ]
      }
    },

    // ===== 4. 项目台账 (M-03) =====
    {
      id: 'ledger',
      code: 'M-03',
      name: '项目台账',
      subtitle: '档案与履约节点',
      group: 'engineering',
      angle: 220,
      color: '#10b981',
      tagColor: '#10b981',
      icon: 'M',
      branches: [
        { id: 'milestone', code: 'B-1', label: '里程碑节点', subtitle: '关键工期与验收节点', isDefault: true },
        { id: 'contracts', code: 'B-2', label: '商务合同档案', subtitle: '总包与补充协议' }
      ],
      data: {
        milestone: [
          {
            id: 'ms-start',
            code: 'MS-01',
            title: '开工准备与地勘交接',
            type: 'milestone',
            desc: '现场三通一平、地勘资料交接与开工报审表监理批复。',
            metrics: [['状态', '已达成 100%'], ['计划时间', '2026-03-01'], ['实际完成', '2026-03-01']],
            msDetail: {
              targetDate: '2026-03-01',
              actualDate: '2026-03-01',
              status: '已达成',
              payTerm: '预付款 10% 到账'
            }
          },
          {
            id: 'ms-struct',
            code: 'MS-02',
            title: '主体结构正负零以下工程',
            type: 'milestone',
            desc: '基坑开挖、独立基础浇筑与地下管网预埋隐蔽工程验收。',
            metrics: [['状态', '已达成 100%'], ['计划时间', '2026-05-15'], ['实际完成', '2026-05-12']],
            msDetail: {
              targetDate: '2026-05-15',
              actualDate: '2026-05-12',
              status: '已达成',
              payTerm: '第一期进度款 85% 计量'
            }
          },
          {
            id: 'ms-roof',
            code: 'MS-03',
            title: '主体结构封顶节点',
            type: 'milestone',
            desc: '主体混凝土框架结构全面封顶，五方责任主体阶段性结构验收。',
            metrics: [['状态', '推进中 80%'], ['计划时间', '2026-10-30'], ['预警状态', '工期正常']],
            msDetail: {
              targetDate: '2026-10-30',
              actualDate: '预计 10-28',
              status: '进行中 (已完成 80%)',
              payTerm: '结构封顶款 20%'
            }
          }
        ],
        contracts: [
          {
            id: 'cnt-main',
            code: 'CT-01',
            title: '建设工程施工总承包合同',
            desc: '示范文本 GF-2017-0201，固定单价计价方式，工期 240 日历天。',
            metrics: [['签约额', '145 万元'], ['履约担保', '已出函'], ['印花税', '已缴纳']]
          }
        ]
      }
    },

    // ===== 5. 财务分析 (F-08) =====
    {
      id: 'finance',
      code: 'F-08',
      name: '财务分析',
      subtitle: '收支流水与现金流对账',
      group: 'operations',
      angle: 70,
      color: '#ef4444',
      tagColor: '#ef4444',
      icon: 'F',
      branches: [
        { id: 'ledger', code: 'B-1', label: '本地对账流水', subtitle: 'MoneyCats 账本导入', isDefault: true },
        { id: 'trend', code: 'B-2', label: '现金流走势', subtitle: '周期预测安全垫' }
      ],
      data: {
        ledger: [
          {
            id: 'fl-1',
            code: 'TR-01',
            title: '西永学校一期进度款到账 (+92.5万)',
            type: 'trans',
            desc: '业主通过国库集中支付中心划拨第一期工程进度计量款。',
            metrics: [['金额', '+925,000 元'], ['类型', '工程回款'], ['状态', '已对账']],
            finDetail: {
              amount: '+925,000.00',
              date: '2026-09-22',
              account: '招商银行基本户 (7892)',
              invoiceStatus: '已开具 9% 增值税专用发票',
              counterparty: '西永微电子产业园区建设局'
            }
          },
          {
            id: 'fl-2',
            code: 'TR-02',
            title: '钢筋水泥主材采购付款 (-48.2万)',
            type: 'trans',
            desc: '支付重庆重钢物资销售有限公司二批次螺纹钢及预拌砂浆采购款。',
            metrics: [['金额', '-482,000 元'], ['类型', '材料支出'], ['状态', '已对账']],
            finDetail: {
              amount: '-482,000.00',
              date: '2026-09-18',
              account: '招商银行基本户 (7892)',
              invoiceStatus: '已收 13% 专票 4 份并认证抵扣',
              counterparty: '重庆重钢物资销售有限公司'
            }
          },
          {
            id: 'fl-3',
            code: 'TR-03',
            title: '安装劳务分包阶段计量款 (-26.0万)',
            type: 'trans',
            desc: '支付四川华西建筑劳务有限公司西永项目 8 月份劳务人工计量款。',
            metrics: [['金额', '-260,000 元'], ['类型', '劳务分包'], ['状态', '已对账']],
            finDetail: {
              amount: '-260,000.00',
              date: '2026-09-15',
              account: '建设银行分包专户 (3401)',
              invoiceStatus: '已收 9% 劳务专票并完成代缴税',
              counterparty: '四川华西建筑劳务有限公司'
            }
          }
        ],
        trend: [
          {
            id: 'fl-pred',
            code: 'CF-01',
            title: '下季度现金流安全垫模拟',
            desc: '预计未来 90 天经营性现金流入 240 万元，必要刚性支出 175 万元，结余安全。',
            metrics: [['安全系数', '1.37'], ['安全维持期', '4.2个月'], ['风险等级', '极低']]
          }
        ]
      }
    },

    // ===== 6. 待办推进 (T-02) =====
    {
      id: 'todos',
      code: 'T-02',
      name: '待办推进',
      subtitle: '任务看板与执行',
      group: 'operations',
      angle: 320,
      color: '#10b981',
      tagColor: '#10b981',
      icon: 'D',
      branches: [
        { id: 'p0', code: 'B-1', label: '紧急待办 (P0)', subtitle: '阻断级任务焦点', isDefault: true },
        { id: 'regular', code: 'B-2', label: '常规推进', subtitle: 'P1/P2 日常排期' }
      ],
      data: {
        p0: [
          {
            id: 'td-xy-qa',
            code: 'TD-01',
            title: '复核西永学校招标文件答疑澄清',
            type: 'task',
            desc: '核实补遗文件中措施项目费计算规则变动，重点核查抗震支吊架清单项。',
            metrics: [['优先级', 'P0 紧急'], ['截止时间', '今日 17:00'], ['状态', '处理中']],
            taskDetail: {
              priority: 'P0 - 阻断级',
              deadline: '今日 17:00 (倒计时 2小时)',
              assignee: '李工 (造价一所)',
              project: '西永L公立学校项目'
            }
          },
          {
            id: 'td-jr-visa',
            code: 'TD-02',
            title: '核算金融城项目超支钢材签证单',
            type: 'task',
            desc: '现场监理已签收变更工程量，需在 48 小时内完成单价套用与增减额申报。',
            metrics: [['优先级', 'P0 紧急'], ['截止时间', '明日 12:00'], ['状态', '待审核']],
            taskDetail: {
              priority: 'P0 - 商务紧急',
              deadline: '明日 12:00',
              assignee: '张总工',
              project: '金融城5号配电工程'
            }
          }
        ],
        regular: [
          {
            id: 'td-inv',
            code: 'TD-03',
            title: '核对上月劳务分包增值税发票',
            type: 'task',
            desc: '财务部月末结账前完成 3 份劳务专票系统抵扣勾选。',
            metrics: [['优先级', 'P1 重要'], ['截止时间', '周五 18:00'], ['状态', '已安排']],
            taskDetail: {
              priority: 'P1 - 业务常规',
              deadline: '本周五 18:00',
              assignee: '财务科',
              project: '公司统一账本'
            }
          }
        ]
      }
    },

    // ===== 7. 速算工具箱 (T-06) =====
    {
      id: 'tools',
      code: 'T-06',
      name: '速算工具箱',
      subtitle: '计算与比对工具',
      group: 'engineering',
      angle: 250,
      color: '#f59e0b',
      tagColor: '#f59e0b',
      icon: 'T',
      branches: [
        { id: 'calc', code: 'B-1', label: '规费税金算器', subtitle: '反推与价税分离', isDefault: true },
        { id: 'diff', code: 'B-2', label: '清单版本比对', subtitle: 'Excel 特征量差' }
      ],
      data: {
        calc: [
          {
            id: 'tc-tax',
            code: 'TC-01',
            title: '规费税金快速换算工具',
            type: 'tool',
            desc: '支持增值税 9%/13% 与城市维护建设税、教育费附加快速联动反推。',
            metrics: [['计算模式', '纯算离线'], ['换算精度', '0.01元'], ['推荐使用', '投标定标']]
          },
          {
            id: 'tc-unbal',
            code: 'TC-02',
            title: '不平衡报价调价计算器',
            type: 'tool',
            desc: '测算在不改变总报价前提下，前调单价对早期工程款现金流的增益曲线。',
            metrics: [['模拟轮次', '多轮试算'], ['安全防线', '自动预警'], ['报表输出', '支持']]
          }
        ],
        diff: [
          {
            id: 'tc-boq-diff',
            code: 'TC-03',
            title: '清单双版本特征量差比对',
            type: 'tool',
            desc: '极速上传比对新旧两版 Excel 清单，标黄工程量变动，标红新增项。',
            metrics: [['比对引擎', '表格双轨'], ['容错匹配', '项目特征'], ['耗时', '<1秒']]
          }
        ]
      }
    }
  ];

// PORTAL_DATA 对象在迁移时丢弃：其 getter 已重写为下方具名导出，
// 避免 this 绑定与重复实现。

export const getModule = (id: string): PortalModule | undefined => MODULES.find((m) => m.id === id);
export const getBranches = (modId: string): PortalBranch[] => getModule(modId)?.branches ?? [];
export const getItems = (modId: string, branchId?: string): PortalItem[] => {
  const m = getModule(modId);
  if (!m || !m.data) return [];
  let target = branchId;
  if (!target && m.branches?.length) {
    target = (m.branches.find((b) => b.isDefault) ?? m.branches[0]).id;
  }
  return (target && m.data[target]) || [];
};
export const getItem = (modId: string, branchId: string, itemId: string): PortalItem | undefined =>
  getItems(modId, branchId).find((it) => it.id === itemId);
