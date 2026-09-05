import { downscaleImage } from '../../lib/imageUtils'
import { uploadAttachment } from '../../api/attachments'
import type { LocalAttachment } from './InputBox'

/** 单轮附件上限(设计 §3.1/§5.1.2,与服务端 B3 一致)。 */
export const MAX_ATTACHMENTS = 4
/** 单张大小上限(与服务端一致,超限不发请求)。 */
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

/** 添加管道的临时行内提示类别(T7 i18n:chat.attachments.maxImages / unsupportedType / tooLarge)。 */
export type AttachmentHint = 'maxImages' | 'unsupportedType' | 'tooLarge'

/** 提示文案(T7:替换为 i18n chat.attachments.* 后删除本表)。 */
const HINT_TEXT: Record<AttachmentHint, string> = {
  maxImages: '最多 4 张',
  unsupportedType: '仅支持 PNG / JPEG / WebP / GIF',
  tooLarge: '图片超过 10MB',
}

export function attachmentHintText(hint: AttachmentHint): string {
  return HINT_TEXT[hint]
}

/** 本地附件 id:优先 crypto.randomUUID(),不可用时递增兜底(jsdom/旧浏览器)。 */
let localSeq = 0
function nextLocalId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  localSeq += 1
  return `att-local-${localSeq}`
}

/** 缩略图预览地址:object URL(jsdom 无 createObjectURL 时退回空串,仅影响测试渲染)。 */
function createPreviewUrl(file: File): string {
  return typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function'
    ? URL.createObjectURL(file)
    : ''
}

/** 单张校验:非 image/* MIME 或超过 10MB → 不发起上传。 */
function validateFile(file: File): AttachmentHint | null {
  if (!file.type.startsWith('image/')) return 'unsupportedType'
  if (file.size > MAX_ATTACHMENT_BYTES) return 'tooLarge'
  return null
}

function isInvalid(file: File): boolean {
  return validateFile(file) !== null
}

/** 对单个附件打补丁;若该项已被移除(不在列表中)则原样返回,不复活它。 */
function patchItem(items: LocalAttachment[], localId: string, patch: Partial<LocalAttachment>): LocalAttachment[] {
  let changed = false
  const next = items.map(a => {
    if (a.localId !== localId) return a
    changed = true
    return { ...a, ...patch }
  })
  return changed ? next : items
}

/** 管道上下文:状态由调用方持有(ChatWindow/InputBox),管道只通过 onChange 同步。 */
export interface AttachmentPipelineCtx {
  /** 读取最新列表(async 续段里必须重读,避免闭包过期覆盖并发修改)。 */
  getCurrent: () => LocalAttachment[]
  /** 同步最新列表。 */
  onChange: (next: LocalAttachment[]) => void
}

/** 单张顺序上传:压缩 → 上传 → ready / failed(设计 §5.1.2:顺序执行,无并发队列)。 */
async function uploadOne(item: LocalAttachment, ctx: AttachmentPipelineCtx): Promise<void> {
  try {
    const scaled = await downscaleImage(item.file)
    const uploaded = await uploadAttachment(scaled)
    ctx.onChange(patchItem(ctx.getCurrent(), item.localId, { status: 'ready', uploaded }))
  } catch {
    ctx.onChange(patchItem(ctx.getCurrent(), item.localId, { status: 'failed' }))
  }
}

/**
 * 共享添加管道(设计 §5.1.2):📎 按钮与拖放 drop 共用,保证行为一致。
 * 1. 现有列表 + 待加数 > 4 → 返回 maxImages 提示,不上传;
 * 2. 逐张校验:非 image/* 或 >10MB → 该张标记 failed(不发请求),收集提示;
 * 3. 通过校验的按顺序 downscaleImage → uploadAttachment → ready,失败转 failed(可重试);
 * 4. 任何状态变化都通过 ctx.onChange 同步最新数组。
 * 返回需要展示的行内提示(无则 null);展示与自动消失由调用方负责。
 */
export async function addFilesToAttachments(
  files: File[],
  ctx: AttachmentPipelineCtx,
): Promise<AttachmentHint | null> {
  const current = ctx.getCurrent()
  if (current.length + files.length > MAX_ATTACHMENTS) return 'maxImages'

  let hint: AttachmentHint | null = null
  const added: LocalAttachment[] = files.map(file => {
    const invalid = isInvalid(file)
    if (invalid) {
      // 首个命中的校验提示优先(类型 > 大小,与校验顺序一致)
      hint ??= validateFile(file)
    }
    return {
      localId: nextLocalId(),
      file,
      status: invalid ? 'failed' : 'uploading',
      previewUrl: createPreviewUrl(file),
    }
  })

  // 先整批插入(strip 立即出现缩略图),再按顺序上传
  ctx.onChange([...current, ...added])
  for (const item of added) {
    if (item.status !== 'uploading') continue
    await uploadOne(item, ctx)
  }
  return hint
}

/**
 * 重试一张失败附件:重新走「校验 → 压缩 → 上传」(校验不过的保持 failed,不静默放行)。
 */
export async function retryLocalAttachment(localId: string, ctx: AttachmentPipelineCtx): Promise<void> {
  const current = ctx.getCurrent()
  const item = current.find(a => a.localId === localId)
  if (!item || item.status !== 'failed') return
  if (isInvalid(item.file)) return
  ctx.onChange(patchItem(current, localId, { status: 'uploading' }))
  await uploadOne(item, ctx)
}

/** 从列表移除一张附件(pure;object URL 的 revoke 由渲染层负责)。 */
export function removeLocalAttachment(current: LocalAttachment[], localId: string): LocalAttachment[] {
  return current.filter(a => a.localId !== localId)
}
