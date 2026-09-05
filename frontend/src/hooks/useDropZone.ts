import { useEffect, useRef, useState } from 'react'

/** 拖入的是否为文件:DataTransfer.types 含 'Files' 才算(码农页代码块拖选不触发蒙层,设计 §5.1.2)。 */
function dragHasFiles(e: DragEvent): boolean {
  const types = e.dataTransfer?.types
  return !!types && Array.from(types).includes('Files')
}

/** 落下的文件里挑出图片(非图片文件直接忽略,不做失败态)。 */
function collectImageFiles(e: DragEvent): File[] {
  const files = Array.from(e.dataTransfer?.files ?? [])
  return files.filter(f => f.type.startsWith('image/'))
}

/**
 * 文档级拖放区(设计 §5.1.2 F4):
 * - document 级监听 dragenter / dragover / dragleave / drop;
 * - dragenter/dragleave 用计数器抵消子元素冒泡(进入子元素触发成对 enter/leave);
 * - dragover 必须 preventDefault 才允许 drop;
 * - 仅当 types 含 'Files' 时置 isDragging=true(由调用方渲染蒙层);
 * - drop 时 preventDefault、取 files 过滤图片后回调,计数器复位;
 * - dragleave 计数归零同样复位;卸载时移除全部监听。
 */
export function useDropZone(onFiles: (files: File[]) => void): { isDragging: boolean } {
  const [isDragging, setIsDragging] = useState(false)
  // 回调放 ref:事件监听只挂一次,始终调用最新回调,避免闭包过期。
  const onFilesRef = useRef(onFiles)
  // enter/leave 计数器:0 = 不在拖拽中。
  const counterRef = useRef(0)
  useEffect(() => {
    onFilesRef.current = onFiles
  })

  useEffect(() => {
    const reset = () => {
      counterRef.current = 0
      setIsDragging(false)
    }
    const onDragEnter = (e: DragEvent) => {
      if (!dragHasFiles(e)) return
      counterRef.current += 1
      setIsDragging(true)
    }
    const onDragOver = (e: DragEvent) => {
      if (!dragHasFiles(e)) return
      // 允许 drop:没有这一步浏览器会把 drop 交给默认行为(打开文件)。
      e.preventDefault()
    }
    const onDragLeave = (e: DragEvent) => {
      if (!dragHasFiles(e)) return
      counterRef.current -= 1
      if (counterRef.current <= 0) reset()
    }
    const onDrop = (e: DragEvent) => {
      if (!dragHasFiles(e)) return
      e.preventDefault()
      const files = collectImageFiles(e)
      reset()
      if (files.length > 0) onFilesRef.current(files)
    }

    document.addEventListener('dragenter', onDragEnter)
    document.addEventListener('dragover', onDragOver)
    document.addEventListener('dragleave', onDragLeave)
    document.addEventListener('drop', onDrop)
    return () => {
      document.removeEventListener('dragenter', onDragEnter)
      document.removeEventListener('dragover', onDragOver)
      document.removeEventListener('dragleave', onDragLeave)
      document.removeEventListener('drop', onDrop)
    }
  }, [])

  return { isDragging }
}
