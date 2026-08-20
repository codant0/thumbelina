// 基于字符类型的 token 数估算 —— 与后端
// src/thumbelina/rag/retrieval/context_formatter.estimate_tokens 口径保持一致：
// CJK 字符按约 2 token/字，其余字符按约 0.25 token/字符（英文平均每 token 约 4 字符）。
// 仅用于展示占位估算，不作为精确计费依据。

// 覆盖 CJK 统一表意文字、扩展区、兼容区、假名、谚文、全角符号等
// 近似后端 unicodedata.east_asian_width() in ("W","F") 的字符集合。
const CJK_RE = /[ᄀ-ᇿ⺀-鿿가-힣豈-﫿︰-﹏＀-｠￠-￦]/

export function estimateTokens(text: string): number {
  let cjk = 0
  for (const ch of text) {
    if (CJK_RE.test(ch)) cjk++
  }
  // int() 截断（同后端），保持两层口径完全一致
  return Math.floor(cjk * 2 + (text.length - cjk) * 0.25)
}

/**
 * 解析 context 窗口上限字符串，如 "128K" → 128000、"1M" → 1000000。
 * 支持可选 K/M 后缀（不区分大小写）；无法解析时返回 null（表示未设置）。
 */
export function parseContextWindow(value?: string | null): number | null {
  if (!value) return null
  const m = /^\s*(\d+)\s*([kKmM])?\s*$/.exec(value)
  if (!m) return null
  const num = parseInt(m[1], 10)
  const suffix = m[2]?.toLowerCase()
  if (suffix === 'k') return num * 1000
  if (suffix === 'm') return num * 1_000_000
  return num
}
