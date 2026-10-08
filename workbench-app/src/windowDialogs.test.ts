import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * W-3 静态门禁：源码里不得再出现 window.alert / confirm / prompt。
 *
 * 为什么需要：这三个原生对话框会在 neo-brutalism 界面弹出系统灰框，且某些环境下
 * 会被浏览器静默拦截/自动放行（→「还没点确定就删了」的误删）。站内已有
 * useConfirm / useToast 两个组件，功能测试测不出「有人又用了 window.confirm」——
 * 因为它功能上完全正常，只是风格破口。故用静态扫描钉住。
 *
 * 豁免：注释与字符串中的提及（本文件自身、组件文档注释）不算——只匹配**调用**形态
 * window.alert( / window.confirm( / window.prompt(。
 */

// 定位 src 目录：cwd 可能是 workbench-app（直接跑）或仓库根（--prefix/--root 跑）。
// 早先用 process.cwd()+'src' 在后者下会扫到仓库根的 Python src/，断言恒真、毫无区分度。
// 故改用「含 App.tsx 才算数」的特征探测，不依赖任何 URL scheme。
function resolveSrc(): string {
  const candidates = [join(process.cwd(), 'src'), join(process.cwd(), 'workbench-app', 'src')];
  for (const c of candidates) {
    if (existsSync(join(c, 'App.tsx'))) return c;
  }
  throw new Error(`未能定位 workbench-app/src（试过：${candidates.join(', ')}）`);
}
const SRC = resolveSrc();
const CALL_RE = /window\.(alert|confirm|prompt)\s*\(/;
const SKIP = new Set(['toast.tsx', 'confirm.tsx', 'confirm.test.tsx', 'toast.test.tsx', 'windowDialogs.test.ts']);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

describe('W-3 静态门禁：不得使用原生 window.alert/confirm/prompt', () => {
  it('src 下所有 .ts/.tsx 都不含原生对话框调用', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
      const base = file.split(/[\\/]/).pop() || '';
      if (SKIP.has(base)) continue;  // 组件自身文档注释里会提到这些名字
      const text = readFileSync(file, 'utf8');
      text.split('\n').forEach((line, i) => {
        // 跳过整行注释
        const trimmed = line.trim();
        if (trimmed.startsWith('*') || trimmed.startsWith('//')) return;
        if (CALL_RE.test(line)) offenders.push(`${relative(process.cwd(), file)}:${i + 1}  ${trimmed.slice(0, 80)}`);
      });
    }
    expect(offenders, '请改用 useConfirm / useToast（见 components/confirm.tsx、toast.tsx）').toEqual([]);
  });

  it('自检：扫描的文件数 > 20（防目录解析错位导致恒 pass）', () => {
    const files = walk(SRC);
    expect(files.length, `仅扫描到 ${files.length} 个文件，SRC=${SRC} —— 路径解析可能又错了`).toBeGreaterThan(20);
  });
});