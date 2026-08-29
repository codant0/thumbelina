/** Helpers for rendering code/JSON payloads inside chat messages.
 *  Kept out of component files so those stay Fast-Refresh friendly. */

/** Minimal structural view of a hast node (react-markdown passes these). */
interface HastNode {
  type: string
  value?: string
  children?: HastNode[]
  properties?: { className?: unknown }
}

/** Recursively collects all text under a hast node. */
export function hastText(node: unknown): string {
  const n = node as HastNode | undefined
  if (!n) return ''
  if (n.type === 'text') return n.value ?? ''
  return (n.children ?? []).map(hastText).join('')
}

/** Finds the fenced-code language (`language-x`) on a hast <pre> node. */
export function hastLang(node: unknown): string {
  const n = node as HastNode | undefined
  const code = n?.children?.find(c => c.type === 'element' && c.properties)
  const classes = Array.isArray(code?.properties?.className)
    ? (code?.properties?.className as unknown[])
    : typeof code?.properties?.className === 'string'
      ? (code.properties.className as string).split(/\s+/)
      : []
  const lang = classes.find(c => typeof c === 'string' && c.startsWith('language-'))
  return typeof lang === 'string' ? lang.slice('language-'.length) : 'text'
}

/** Clipboard write with a legacy fallback (jsdom / insecure contexts). */
export async function writeToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

/** Splits a message whose body *starts* with a JSON payload followed by
 *  natural text (e.g. raw memory-extractor output leaked into a reply).
 *  Returns `{ json, rest }` or null when there is no leading JSON value. */
export function splitLeadingJson(text: string): { json: string; rest: string } | null {
  const trimmed = text.trimStart()
  const first = trimmed[0]
  if (first !== '{' && first !== '[') return null
  let depth = 0
  let inString = false
  let escaped = false
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i]
    if (inString) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') inString = true
    else if (ch === '{' || ch === '[') depth++
    else if (ch === '}' || ch === ']') {
      depth--
      if (depth === 0) {
        const json = trimmed.slice(0, i + 1)
        try {
          const parsed = JSON.parse(json)
          if (typeof parsed === 'object' && parsed !== null) {
            return { json, rest: trimmed.slice(i + 1).trimStart() }
          }
        } catch { /* keep scanning deeper */ }
      }
    }
  }
  return null
}

/** True when `text` is exactly one parseable JSON object/array value. */
export function looksLikeJson(text: string): boolean {
  const trimmed = text.trim()
  if (trimmed.length < 12) return false
  if (!/^[{[]/.test(trimmed) || !/[}\]]$/.test(trimmed)) return false
  try {
    const parsed = JSON.parse(trimmed)
    return typeof parsed === 'object' && parsed !== null
  } catch {
    return false
  }
}
