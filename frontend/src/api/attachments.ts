// 附件 API 客户端(设计 §4.3):客户端直传 + 引用发送。
// 上传走 multipart/form-data,不返回 url——前端按 attachmentUrl(id) 自拼,
// 避免 url 与部署路径耦合。

const API_BASE = '/api/v1'

/** POST /api/v1/attachments 响应体;服务端按文件头解析尺寸,失败时 width/height 为 null。 */
export interface UploadedAttachment {
  id: string
  mime: string
  size: number
  width: number | null
  height: number | null
  sha256: string | null
}

/** 上传单个附件(file 可为压缩重编码后的 Blob),可选 alt 描述文本。 */
export async function uploadAttachment(file: Blob, alt?: string): Promise<UploadedAttachment> {
  const form = new FormData()
  form.append('file', file)
  if (alt !== undefined) form.append('alt', alt)
  const res = await fetch(`${API_BASE}/attachments`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<UploadedAttachment>
}

/** 附件取图地址(设计 §4.3):GET /api/v1/attachments/{id},私有缓存一天。 */
export function attachmentUrl(id: string): string {
  return `${API_BASE}/attachments/${id}`
}
