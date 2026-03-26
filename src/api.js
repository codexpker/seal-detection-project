const BASE = ''
 
export async function fetchHealth() {
  const res = await fetch(`${BASE}/api/health`)
  return res.json()
}
 
export async function fetchHomeCurrent() {
  const res = await fetch(`${BASE}/api/home/current`)
  return res.json()
}

export async function fetchHomeDeviceTicker(limit = 50) {
  const res = await fetch(`${BASE}/api/home/device-ticker?limit=${limit}`)
  return res.json()
}

export async function fetchDeviceStats() {
  const res = await fetch(`${BASE}/api/device/stats`)
  return res.json()
}

export async function fetchDeviceIds(page = 1, pageSize = 200, sortBy = 'count', sortOrder = 'desc', devNum = '') {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort_by: sortBy,
    sort_order: sortOrder,
    dev_num: devNum,
  })
  const res = await fetch(`${BASE}/api/device/ids?${query.toString()}`)
  return res.json()
}

export async function fetchAdminRecent(page = 1, pageSize = 50, status = 'all', sortBy = 'time', sortOrder = 'desc', devNum = '') {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    status,
    sort_by: sortBy,
    sort_order: sortOrder,
    dev_num: devNum,
  })
  const res = await fetch(`${BASE}/api/admin/recent?${query.toString()}`)
  return res.json()
}

export async function fetchFaultRecent(limit = 100, devNum = '', hours = 0) {
  const query = new URLSearchParams({
    limit: String(limit),
    dev_num: devNum,
    hours: String(hours),
  })
  const res = await fetch(`${BASE}/api/fault/recent?${query.toString()}`)
  return res.json()
}

export function buildFaultRecentExportUrl(limit = 1000, devNum = '', hours = 0) {
  const query = new URLSearchParams({
    limit: String(limit),
    dev_num: devNum,
    hours: String(hours),
  })
  return `${BASE}/api/fault/recent/export?${query.toString()}`
}

export async function fetchDeviceModel(devNum) {
  const res = await fetch(`${BASE}/api/device/${encodeURIComponent(devNum)}/model`)
  return res.json()
}

export async function selectDeviceModel(devNum, modelName) {
  const res = await fetch(`${BASE}/api/device/${encodeURIComponent(devNum)}/model/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_name: modelName }),
  })
  return res.json()
}
 
export async function fetchDeviceCurve(devNum, hours = 48, endTs = null, pointsLimit = null) {
  const query = new URLSearchParams({ hours: String(hours) })
  if (endTs) query.set('end_ts', String(endTs))
  if (pointsLimit) query.set('points_limit', String(pointsLimit))
  const res = await fetch(`${BASE}/api/device/detail/${encodeURIComponent(devNum)}?${query.toString()}`)
  return res.json()
}
 
export async function fetchDeviceAnomalies(devNum, hours = 48) {
  const res = await fetch(`${BASE}/api/device/${encodeURIComponent(devNum)}/anomalies?hours=${hours}`)
  return res.json()
}
 
export async function fetchDiagnosisRecent(limit = 200) {
  const res = await fetch(`${BASE}/api/diagnosis/recent?limit=${limit}`)
  return res.json()
}

export async function startDiagnosisReplay(devNum, startTs, endTs, modelName = 'auto') {
  const res = await fetch(`${BASE}/api/diagnosis/replay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dev_num: devNum, start_ts: startTs, end_ts: endTs, model_name: modelName }),
  })
  return res.json()
}

export async function fetchDiagnosisReplayStatus(taskId) {
  const res = await fetch(`${BASE}/api/diagnosis/replay/${encodeURIComponent(taskId)}`)
  return res.json()
}

export async function fetchRuntimeMetrics() {
  const res = await fetch(`${BASE}/api/runtime/metrics`)
  return res.json()
}
 
export async function fetchDiagnosisDevice(devNum, hours = 24) {
  const res = await fetch(`${BASE}/api/diagnosis/device/${encodeURIComponent(devNum)}?hours=${hours}`)
  return res.json()
}
 
export async function fetchModels() {
  const res = await fetch(`${BASE}/api/models`)
  return res.json()
}
 
export async function selectModel(modelName) {
  const res = await fetch(`${BASE}/api/models/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_name: modelName }),
  })
  return res.json()
}

export async function rollbackModelVersion(modelName, targetVersion) {
  const res = await fetch(`${BASE}/api/models/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_name: modelName, target_version: targetVersion }),
  })
  return res.json()
}
 
export async function triggerProcess(devNum, deviceTimestamp) {
  const res = await fetch(`${BASE}/api/internal/process/${encodeURIComponent(devNum)}/${deviceTimestamp}`, {
    method: 'POST',
  })
  return res.json()
}

export async function uploadLocalXlsx(file, modelName = 'seal_v4', devNumHint = '', processMode = 'full') {
  const form = new FormData()
  form.append('file', file)
  form.append('model_name', modelName)
  form.append('dev_num_hint', devNumHint)
  form.append('process_mode', processMode)
  const res = await fetch(`${BASE}/api/upload/xlsx`, {
    method: 'POST',
    body: form,
  })
  return res.json()
}
 
export function createHomeSSE() {
  return new EventSource(`${BASE}/api/home/stream`)
}
 
export function createDiagSSE() {
  return new EventSource(`${BASE}/api/diagnosis/stream`)
}
