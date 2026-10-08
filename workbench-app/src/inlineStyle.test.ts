import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * W-2 守卫：不得再写「整块恰被既有工具类完全覆盖」的内联 style。
 *
 * 背景（W-2 实测重估）
 * -------------------
 * 全仓 345 个内联 style 块里，仅有 10 块能被现有工具类（.flex/.gap-2/.mt-3/...）
 * 整块替代——已全部转成 className。其余 335 块含 fontSize / 动态值 / 一次性微调，
 * 属合理用法（不动）。本守卫只钉那**确定该转**的一类：整块的每个属性都在工具类
 * 覆盖表里，却仍写成内联 —— 这是纯粹的重复劳动，新人照抄会让内联面重新膨胀。
 *
 * 为什么不用「内联块数上限」当判据：那会逼人为了数字去动合理的 fontSize，
 * 反而更糟。只禁可整块替代的，边界清晰、零误伤。
 */

function resolveSrc(): string {
  for (const c of [join(process.cwd(), 'src'), join(process.cwd(), 'workbench-app', 'src')]) {
    if (existsSync(join(c, 'App.tsx'))) return c;
  }
  throw new Error('未能定位 workbench-app/src');
}
const SRC = resolveSrc();

// 工具类覆盖表（与 global.css 实际定义一致；值取自 tokens 间距）
const UTIL: Record<string, string> = {
  'display:flex': 'flex', "display:'flex'": 'flex',
  "flexDirection:'column'": 'flex-col',
  "alignItems:'center'": 'items-center',
  "justifyContent:'space-between'": 'justify-between',
  'gap:8': 'gap-2', 'gap:16': 'gap-3', 'gap:24': 'gap-4',
  "width:'100%'": 'w-full', 'width:"100%"': 'w-full',
  "textAlign:'center'": 'text-center',
  'marginTop:8': 'mt-2', 'marginTop:16': 'mt-3', 'marginTop:24': 'mt-4',
  'marginBottom:8': 'mb-2', 'marginBottom:16': 'mb-3', 'marginBottom:24': 'mb-4',
};
const norm = (s: string) => s.replace(/\s+/g, '').replace(/"/g, "'");

function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const f = join(dir, n);
    if (statSync(f).isDirectory()) walk(f, out);
    else if (/\.tsx?$/.test(n) && !/\.test\./.test(n)) out.push(f);
  }
  return out;
}

describe('W-2 守卫：无「整块可被工具类替代」的内联 style', () => {
  it('扫描根正确（> 20 个文件）', () => {
    expect(walk(SRC).length).toBeGreaterThan(20);
  });

  it('不存在整块可转工具类的内联 style', () => {
    const offenders: string[] = [];
    for (const f of walk(SRC)) {
      const text = readFileSync(f, 'utf8');
      const re = /style=\{\{([^}]*)\}\}/gs;
      let m: RegExpExecArray | null;
      while ((m = re.exec(text))) {
        const parts = m[1].split(',').map((s) => s.trim()).filter(Boolean);
        if (!parts.length) continue;
        const classes: string[] = [];
        let allCovered = true;
        for (const p of parts) {
          const c = UTIL[norm(p)];
          if (c) classes.push(c);
          else { allCovered = false; break; }
        }
        if (allCovered && classes.length) {
          const line = text.slice(0, m.index).split('\n').length;
          offenders.push(`${relative(process.cwd(), f)}:${line} → 改用 className="${classes.join(' ')}"`);
        }
      }
    }
    expect(offenders, '整块可被工具类替代却仍写内联（W-2）：').toEqual([]);
  });
});