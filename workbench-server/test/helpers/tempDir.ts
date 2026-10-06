import { rmSync } from 'node:fs';

/**
 * 测试临时目录的尽力清理。
 *
 * better-sqlite3 会以 WAL 模式持有模块级连接，持续占用 .db-wal / .db-shm 文件句柄；
 * Windows 不允许删除仍被占用的文件，rmSync 会抛 EPERM（POSIX 允许 unlink 已打开文件，故 Linux 无此问题）。
 * 因此在 Windows 上吞掉删除失败，残留目录被限制在 %TEMP% 内，交由系统回收；
 * 其他平台仍让真实错误抛出，避免掩盖缺陷。
 */
export function cleanupTempDir(dir: string | undefined): void {
  if (!dir) return;
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch (error) {
    if (process.platform !== 'win32') throw error;
  }
}
