/**
 * frontend/src/modules/admin/catalogTemplateDownload.js
 * STORE-13: one place that downloads the product spreadsheet template (used by the import window and the empty Products screen).
 * Throws when the template cannot be fetched; callers show their own message.
 */
import * as adminSvc from '../../services/admin.service'

export async function downloadImportTemplate() {
  const text = await adminSvc.getCatalogImportTemplate()
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'opsra-products-template.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
