import { describe, it, expect, vi, beforeEach } from 'vitest'
import { uploadAttachment, attachmentUrl } from './attachments'

function mockJson(data: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(data), { status }),
  )
}

describe('attachments api', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uploadAttachment posts multipart/form-data to /attachments (file + 可选 alt)', async () => {
    const spy = mockJson({ id: 'att_1', mime: 'image/jpeg', size: 10, width: 100, height: 80, sha256: null })
    const uploaded = await uploadAttachment(new Blob(['img-bytes'], { type: 'image/jpeg' }), '截图')
    expect(uploaded.id).toBe('att_1')
    expect(uploaded.width).toBe(100)
    const url = spy.mock.calls[0][0] as string
    expect(url).toBe('/api/v1/attachments')
    const init = spy.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    const body = init.body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('file')).toBeInstanceOf(Blob)
    expect(body.get('alt')).toBe('截图')
  })

  it('uploadAttachment omits alt field when not provided', async () => {
    const spy = mockJson({ id: 'att_2', mime: 'image/png', size: 1, width: null, height: null, sha256: 'abc' })
    await uploadAttachment(new Blob(['x']))
    const body = (spy.mock.calls[0][1] as RequestInit).body as FormData
    expect(body.get('alt')).toBeNull()
  })

  it('uploadAttachment throws Error with backend detail on failure', async () => {
    mockJson({ detail: '文件类型不支持' }, 415)
    await expect(uploadAttachment(new Blob(['x']))).rejects.toThrow('文件类型不支持')
  })

  it('uploadAttachment falls back to HTTP status when detail is missing', async () => {
    mockJson({}, 500)
    await expect(uploadAttachment(new Blob(['x']))).rejects.toThrow('HTTP 500')
  })

  it('attachmentUrl builds /api/v1/attachments/{id}', () => {
    expect(attachmentUrl('att_xxx')).toBe('/api/v1/attachments/att_xxx')
  })
})
