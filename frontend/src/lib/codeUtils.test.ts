import { describe, it, expect } from 'vitest'
import { splitLeadingJson, looksLikeJson, hastText } from './codeUtils'

describe('looksLikeJson', () => {
  it('accepts a bare JSON object', () => {
    expect(looksLikeJson('{"action":"NEW","entry":{"title":"用户称呼习惯","slug":"a"}}')).toBe(true)
  })
  it('rejects short strings and non-JSON', () => {
    expect(looksLikeJson('hello world')).toBe(false)
    expect(looksLikeJson('{not json}')).toBe(false)
    expect(looksLikeJson('{}')).toBe(false) // below length threshold
  })
})

describe('splitLeadingJson', () => {
  it('splits JSON followed by natural text', () => {
    const src = '{"a":1,"b":{"c":[1,2]}}\nDone! I remembered it.'
    const out = splitLeadingJson(src)
    expect(out).not.toBeNull()
    expect(JSON.parse(out!.json)).toEqual({ a: 1, b: { c: [1, 2] } })
    expect(out!.rest).toBe('Done! I remembered it.')
  })
  it('handles braces inside strings', () => {
    const src = '{"note":"has { and } chars"} trailing'
    const out = splitLeadingJson(src)
    expect(JSON.parse(out!.json).note).toBe('has { and } chars')
    expect(out!.rest).toBe('trailing')
  })
  it('returns null without leading JSON', () => {
    expect(splitLeadingJson('plain text')).toBeNull()
    expect(splitLeadingJson('{"broken": ')).toBeNull()
  })
})

describe('hastText', () => {
  it('collects nested text nodes', () => {
    const node = {
      type: 'element',
      children: [
        { type: 'text', value: 'foo ' },
        { type: 'element', children: [{ type: 'text', value: 'bar' }] },
      ],
    }
    expect(hastText(node)).toBe('foo bar')
  })
  it('handles undefined', () => {
    expect(hastText(undefined)).toBe('')
  })
})
