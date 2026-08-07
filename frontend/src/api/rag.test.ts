import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  uploadFilesAsync,
  uploadUrlAsync,
  listUploadTasks,
  cancelUploadTask,
} from './rag'

function mockJson(data: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(data), { status }),
  )
}

describe('rag upload task api', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uploadFilesAsync posts single file to /documents', async () => {
    const spy = mockJson({ task_id: 't1' }, 202)
    const id = await uploadFilesAsync('kb1', [new File(['x'], 'a.md')])
    expect(id).toBe('t1')
    const url = spy.mock.calls[0][0] as string
    expect(url.endsWith('/knowledge-bases/kb1/documents')).toBe(true)
    const body = spy.mock.calls[0][1]?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
  })

  it('uploadFilesAsync posts multiple files to /documents/batch', async () => {
    const spy = mockJson({ task_id: 't2' }, 202)
    await uploadFilesAsync('kb1', [new File(['x'], 'a.md'), new File(['y'], 'b.md')])
    const url = spy.mock.calls[0][0] as string
    expect(url.endsWith('/documents/batch')).toBe(true)
    const body = spy.mock.calls[0][1]?.body as FormData
    expect(body.getAll('files')).toHaveLength(2)
  })

  it('uploadUrlAsync posts url', async () => {
    const spy = mockJson({ task_id: 't3' }, 202)
    await uploadUrlAsync('kb1', 'https://example.com')
    const url = spy.mock.calls[0][0] as string
    expect(url.endsWith('/documents/url')).toBe(true)
    const body = JSON.parse(spy.mock.calls[0][1]?.body as string) as { url: string }
    expect(body.url).toBe('https://example.com')
  })

  it('uploadFilesAsync rejects empty file list', async () => {
    await expect(uploadFilesAsync('kb1', [])).rejects.toThrow('No files to upload')
  })

  it('listUploadTasks returns tasks', async () => {
    mockJson([{ id: 't1', status: 'running' }])
    const tasks = await listUploadTasks('kb1')
    expect(tasks).toHaveLength(1)
    expect(tasks[0].id).toBe('t1')
  })

  it('cancelUploadTask calls DELETE', async () => {
    const spy = mockJson({ cancelled: true })
    await cancelUploadTask('t1')
    const init = spy.mock.calls[0][1]
    expect(init?.method).toBe('DELETE')
  })

  it('uploadFilesAsync throws on error detail', async () => {
    mockJson({ detail: 'Unsupported file type' }, 400)
    await expect(
      uploadFilesAsync('kb1', [new File(['x'], 'a.exe')]),
    ).rejects.toThrow('Unsupported file type')
  })
})
