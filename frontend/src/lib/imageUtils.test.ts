import { describe, it, expect, vi, afterEach } from 'vitest'
import { downscaleImage } from './imageUtils'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('downscaleImage', () => {
  it('小图(≤800KB)原样返回,不走解码/重编码', async () => {
    const file = new File(['tiny'], 'small.png', { type: 'image/png' })
    await expect(downscaleImage(file)).resolves.toBe(file)
  })

  it('非图片 MIME 原样返回(即使体积超阈值)', async () => {
    const file = new File([new Uint8Array(900 * 1024)], 'doc.bin', {
      type: 'application/octet-stream',
    })
    await expect(downscaleImage(file)).resolves.toBe(file)
  })

  it('大图走 canvas 重编码:输出 .jpg / image/jpeg,最长边压到 2048,并释放位图', async () => {
    const close = vi.fn()
    const bitmap = { width: 4096, height: 2048, close }
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue(bitmap))
    const drawImage = vi.fn()
    class FakeOffscreenCanvas {
      width: number
      height: number
      constructor(width: number, height: number) {
        this.width = width
        this.height = height
      }
      getContext() {
        return { drawImage }
      }
      convertToBlob() {
        return Promise.resolve(new Blob(['jpeg-bytes'], { type: 'image/jpeg' }))
      }
    }
    vi.stubGlobal('OffscreenCanvas', FakeOffscreenCanvas)

    const file = new File([new Uint8Array(900 * 1024)], 'photo.png', { type: 'image/png' })
    const out = await downscaleImage(file)

    expect(vi.mocked(createImageBitmap)).toHaveBeenCalledWith(file)
    expect(out).not.toBe(file)
    expect(out.type).toBe('image/jpeg')
    expect(out.name).toBe('photo.jpg')
    // 4096x2048 → 最长边缩到 2048(等比,不放大)
    expect(drawImage).toHaveBeenCalledWith(bitmap, 0, 0, 2048, 1024)
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('解码不可用(createImageBitmap 缺失且 object URL 不可用)时原样返回兜底', async () => {
    vi.stubGlobal('createImageBitmap', undefined)
    // 去掉 URL.createObjectURL,模拟无 object URL 的受限环境
    vi.stubGlobal('URL', class FakeURL {} as unknown as typeof URL)
    const file = new File([new Uint8Array(900 * 1024)], 'photo.png', { type: 'image/png' })
    await expect(downscaleImage(file)).resolves.toBe(file)
  })
})
