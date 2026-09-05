// 客户端图片压缩(设计 §3.1 F2):大于 800KB 的图片按最长边 2048 等比缩放并重编码为
// JPEG(quality 0.85)。canvas 重编码天然剥离 EXIF(GPS/设备指纹不外传),并保证
// 转成 base64 后低于 Anthropic 5MB 单图上限。仅用浏览器原生 API,不引入依赖。

/** 小于该字节数的图片直接原样上传(重编码得不偿失)。 */
const SKIP_THRESHOLD_BYTES = 800 * 1024
/** 重编码后最长边上限(像素);原图更小时不放大,仅重编码以剥 EXIF。 */
const MAX_EDGE_PX = 2048
/** JPEG 编码质量。 */
const JPEG_QUALITY = 0.85

/** 重编码输出文件名:扩展名替换为 .jpg(无扩展名/异常名退回 image.jpg)。 */
function toJpgName(name: string): string {
  const stem = name.replace(/\.[^.]+$/, '')
  return stem ? `${stem}.jpg` : 'image.jpg'
}

/** 解码结果:统一 ImageBitmap 与 <img> 两条路径的绘制/释放接口。 */
interface DecodedImage {
  width: number
  height: number
  draw: (ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, w: number, h: number) => void
  release: () => void
}

/** 解码图片:首选 createImageBitmap;不可用或失败时降级 object URL + <img>。失败返回 null。 */
async function decodeImage(file: File): Promise<DecodedImage | null> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file)
      return {
        width: bitmap.width,
        height: bitmap.height,
        draw: (ctx, w, h) => { ctx.drawImage(bitmap, 0, 0, w, h) },
        release: () => { bitmap.close() },
      }
    } catch {
      // 解码失败(如浏览器不支持的格式)走 <img> 降级
    }
  }
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') return null
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('image decode failed'))
      img.src = url
    })
    return {
      width: img.naturalWidth,
      height: img.naturalHeight,
      draw: (ctx, w, h) => { ctx.drawImage(img, 0, 0, w, h) },
      release: () => { /* objectURL 已在下方 finally 释放,图片解码完成即不受影响 */ },
    }
  } catch {
    return null
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** 创建画布:优先 OffscreenCanvas(不进 DOM),降级 DOM canvas;两者都不可用返回 null。 */
function createCanvas(w: number, h: number): {
  canvas: OffscreenCanvas | HTMLCanvasElement
  ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D
} | null {
  if (typeof OffscreenCanvas === 'function') {
    const canvas = new OffscreenCanvas(w, h)
    const ctx = canvas.getContext('2d')
    if (ctx) return { canvas, ctx }
  }
  if (typeof document !== 'undefined') {
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (ctx) return { canvas, ctx }
  }
  return null
}

/** 画布导出 JPEG Blob:OffscreenCanvas 用 convertToBlob,DOM canvas 用 toBlob。 */
function canvasToJpegBlob(canvas: OffscreenCanvas | HTMLCanvasElement): Promise<Blob> {
  if ('convertToBlob' in canvas) {
    return canvas.convertToBlob({ type: 'image/jpeg', quality: JPEG_QUALITY })
  }
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      blob => (blob ? resolve(blob) : reject(new Error('canvas.toBlob returned null'))),
      'image/jpeg',
      JPEG_QUALITY,
    )
  })
}

/**
 * 客户端压缩入口:
 * - ≤800KB 或非图片 MIME → 原样返回(不重编码);
 * - 否则解码 → canvas 按最长边 2048 等比缩放(小图不放大)→ 重编码 JPEG → 新 File(.jpg);
 * - 解码/编码任一步不可用或失败 → 原样返回(上传端还有 10MB 限制兜底)。
 * 重编码不拷贝原始字节,EXIF(GPS/设备指纹)由此天然剥离。
 */
export async function downscaleImage(file: File): Promise<File> {
  if (file.size <= SKIP_THRESHOLD_BYTES || !file.type.startsWith('image/')) return file

  const decoded = await decodeImage(file)
  if (!decoded) return file
  try {
    const scale = Math.min(1, MAX_EDGE_PX / Math.max(decoded.width, decoded.height))
    const w = Math.max(1, Math.round(decoded.width * scale))
    const h = Math.max(1, Math.round(decoded.height * scale))
    const painted = createCanvas(w, h)
    if (!painted) return file
    decoded.draw(painted.ctx, w, h)
    const blob = await canvasToJpegBlob(painted.canvas)
    return new File([blob], toJpgName(file.name), { type: 'image/jpeg' })
  } catch {
    // 编码环节失败(画布/导出不可用等):原样返回,不阻断发送流程
    return file
  } finally {
    decoded.release()
  }
}
