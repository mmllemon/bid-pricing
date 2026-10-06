import { chmodSync, mkdirSync, existsSync, statSync } from 'node:fs';

// Windows 没有 POSIX 权限位：chmod 只会切换只读属性，设不出 0700/0600。
// 本机单用户运行时以用户目录的 NTFS ACL 作为隐私边界，因此仅在 POSIX 平台收紧权限。
const POSIX_PERMISSIONS = process.platform !== 'win32';

export function ensurePrivateDir(dir: string): void {
  mkdirSync(dir, { recursive: true });
  if (!POSIX_PERMISSIONS) return;
  try {
    chmodSync(dir, 0o700);
  } catch {
    /* ignore if chmod unsupported */
  }
}

export function ensurePrivateFile(path: string): void {
  if (!existsSync(path)) return;
  if (!POSIX_PERMISSIONS) return;
  try {
    chmodSync(path, 0o600);
  } catch {
    /* ignore */
  }
}

export function modeOf(path: string): number | null {
  try {
    return statSync(path).mode & 0o777;
  } catch {
    return null;
  }
}
