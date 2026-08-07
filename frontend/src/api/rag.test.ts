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
    expect(spy.mock.calls[0][0]).toContain('/knowledge-bases/kb1/documents')
  })

  it('uploadFilesAsync posts multiple files to /documents/batch', async () => {
    const spy = mockJson({ task_id: 't2' }, 202)
    await uploadFilesAsync('kb1', [new File(['x'], 'a.md'), new File(['y'], 'b.md')])
    expect(spy.mock.calls[0][0]).toContain('/documents/batch')
  })

  it('uploadUrlAsync posts url', async () => {
    const spy = mockJson({ task_id: 't3' }, 202)
    await uploadUrlAsync('kb1', 'https://example.com')
    expect(spy.mock.calls[0][0]).toContain('/documents/url')
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
