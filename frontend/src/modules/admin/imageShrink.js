/**
 * frontend/src/modules/admin/imageShrink.js
 * STORE-12: phone photos are often 4-10 MB and the limit is 5 MB. Big pictures are redrawn smaller in the browser
 * (longest side 2000 px, JPEG) before upload. Any failure returns the original file unchanged, so the normal size
 * message is shown instead. Browser-only (needs canvas); not covered by the node tests.
 */
export const SHRINK_ABOVE = 4 * 1024 * 1024
export const LONGEST_SIDE = 2000

export async function shrinkImage(file) {
  try {
    if (!file || file.size <= SHRINK_ABOVE || !/^image\/(jpeg|png|webp)$/.test(file.type)) return file
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, LONGEST_SIDE / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    if (bitmap.close) bitmap.close()
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
    if (!blob || blob.size >= file.size) return file
    return new File([blob], file.name.replace(/\.[A-Za-z0-9]+$/, '') + '.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  }
}
