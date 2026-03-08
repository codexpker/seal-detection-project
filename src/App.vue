<template>
  <div id="seal-app">
    <header class="app-header">
      <h1>电机接线盒智能故障检测系统</h1>
      <nav class="nav-tabs">
        <button class="nav-tab" :class="{ active: page === 'home' }" @click="page = 'home'">实时主页</button>
        <button class="nav-tab" :class="{ active: page === 'device' }" @click="page = 'device'">设备查询</button>
        <button class="nav-tab" :class="{ active: page === 'admin' }" @click="page = 'admin'">管理页面</button>
        <button class="nav-tab" :class="{ active: page === 'diag' }" @click="page = 'diag'">诊断测试</button>
      </nav>
    </header>

    <main class="main-content">
      <section v-if="page === 'home'">
        <div class="home-layout">
          <div class="home-main">
            <div class="card">
              <div class="status-bar">
                <div class="status-item">
                  <span class="status-label">后端状态</span>
                  <span class="status-value">
                    <span v-if="health === null" class="loading-spinner"></span>
                    <span v-else-if="health" class="badge badge-ok">UP</span>
                    <span v-else class="badge badge-anomaly">DOWN</span>
                  </span>
                </div>
                <div class="status-item">
                  <span class="status-label">当前设备</span>
                  <span class="status-value">{{ homeDev || '--' }}</span>
                </div>
                <div class="status-item">
                  <span class="status-label">检测状态</span>
                  <span class="status-value">
                    <span v-if="homeDetection" :class="['badge', homeDetection.is_anomaly ? 'badge-anomaly' : 'badge-ok']">
                      {{ homeDetection.is_anomaly ? '异常' : '正常' }}
                    </span>
                    <span v-else class="badge badge-muted">--</span>
                  </span>
                </div>
                <div class="status-item">
                  <span class="status-label">模型（首页固定）</span>
                  <span class="status-value">{{ homeDetection?.model_name || 'auto' }}</span>
                </div>
                <div class="status-item">
                  <span class="status-label">剩余展示</span>
                  <span class="status-value">
                    <span v-if="homeRemain > 0">{{ homeRemain }}s</span>
                    <span v-else class="badge badge-warning">暂时没有新的数据（当前为最近一次结果）</span>
                  </span>
                </div>
                <div class="status-item">
                  <span class="status-label">最后更新</span>
                  <span class="status-value">{{ homeLastUpdateTs ? formatTime(homeLastUpdateTs) : '--' }}</span>
                </div>
              </div>
            </div>

            <div class="card">
              <h3 class="card-title">实时曲线</h3>
              <TrendChart v-if="homeSeries.length" :series="homeSeries" :marks="homeMarks" />
              <div v-else class="no-data">暂无实时数据，等待设备上报或手动触发检测...</div>
            </div>

            <div class="card">
              <h3 class="card-title">手动触发检测（联调测试）</h3>
              <div class="device-input-row">
                <div class="form-group">
                  <label>设备编号</label>
                  <input class="input" v-model="triggerDev" placeholder="例如 000000020165453" />
                </div>
                <div class="form-group">
                  <label>时间戳 (ms)</label>
                  <input class="input" v-model="triggerTs" :placeholder="String(Date.now())" />
                </div>
                <button class="btn-primary cursor-pointer" @click="doTrigger" :disabled="triggering">
                  {{ triggering ? '处理中...' : '触发检测' }}
                </button>
              </div>
              <div v-if="triggerResult" class="json-box">{{ JSON.stringify(triggerResult, null, 2) }}</div>
            </div>
          </div>

          <aside class="home-right">
            <div class="card home-device-circle-card">
              <h3 class="card-title">设备总览</h3>
              <button class="device-count-circle cursor-pointer" @click="showDeviceIdModal = true" title="点击查看全部设备ID">
                <span class="device-count-value">{{ deviceCount }}</span>
                <span class="device-count-label">设备总数</span>
              </button>
              <div class="device-count-hint">点击圆环查看设备ID列表</div>
            </div>

            <div class="card">
              <h3 class="card-title">设备上报轮播（异常高亮）</h3>
              <div v-if="tickerItems.length" class="ticker-panel">
                <div class="ticker-current" :class="{ anomaly: tickerCurrent?.is_anomaly }">
                  <div class="ticker-dev table-link cursor-pointer" @click="goToDeviceFromTicker(tickerCurrent)">{{ tickerCurrent?.dev_num }}</div>
                  <div class="ticker-meta">
                    <span :class="['badge', tickerCurrent?.is_anomaly ? 'badge-anomaly' : 'badge-ok']">
                      {{ tickerCurrent?.is_anomaly ? '异常' : '正常' }}
                    </span>
                    <span class="ticker-time">{{ formatTime(tickerCurrent?.device_timestamp) }}</span>
                  </div>
                  <div class="ticker-sub">{{ tickerCurrent?.model_name }} | {{ tickerCurrent?.status }}</div>
                </div>

                <div class="ticker-list">
                  <div class="ticker-row" v-for="(item, idx) in tickerItems.slice(0, 12)" :key="item.dev_num + '_' + idx">
                    <button class="ticker-row-dev table-link cursor-pointer" @click="goToDeviceFromTicker(item)">{{ item.dev_num }}</button>
                    <span :class="['badge', item.is_anomaly ? 'badge-anomaly' : 'badge-ok']">
                      {{ item.is_anomaly ? '异常' : '正常' }}
                    </span>
                  </div>
                </div>
              </div>
              <div v-else class="no-data" style="height: 240px">暂无设备轮播数据</div>
            </div>
          </aside>
        </div>
      </section>

      <section v-if="page === 'device'">
        <div class="card">
          <h3 class="card-title">设备历史查询（默认48小时）</h3>
          <div class="device-input-row">
            <div class="form-group">
              <label>设备编号</label>
              <input class="input" v-model="queryDev" placeholder="例如 000000020165453" />
            </div>
            <div class="form-group">
              <label>小时数</label>
              <input class="input" v-model.number="queryHours" type="number" min="1" max="8760" />
            </div>
            <button class="btn-primary" @click="doQueryDevice" :disabled="querying">{{ querying ? '查询中...' : '查询' }}</button>
          </div>
          <div v-if="deviceQueryMessage" class="status-label" style="color:var(--color-warning);margin-top:-8px;margin-bottom:12px;">{{ deviceQueryMessage }}</div>

          <div v-if="!modelServiceAvailable || deviceSelectedModel === 'none'" class="status-label" style="color:var(--color-warning);margin-bottom:10px;">
            {{ !modelServiceAvailable ? (modelServiceMessage || '当前未提供 xgboost/gru 模型，模型切换已禁用，仅支持 none 查询模式') : '当前为 none 模式：仅查询数据，不切换模型' }}
          </div>

          <div class="device-input-row" style="margin-bottom:0">
            <div class="form-group">
              <label>该设备模型</label>
              <select class="model-select" v-model="deviceSelectedModel">
                <option value="none">none（仅查询，不切换模型）</option>
                <option
                  v-for="m in modelCatalog"
                  :key="m.model_name"
                  :value="m.model_name"
                  :disabled="!m.enabled"
                  :class="{ 'model-option-disabled': !m.enabled }"
                >
                  {{ m.model_name }}{{ m.enabled ? '' : '（未提供）' }}
                </option>
              </select>
            </div>
            <button class="btn-primary cursor-pointer" @click="saveDeviceModel" :disabled="switchingDeviceModel || !queryDev.trim() || !modelServiceAvailable || deviceSelectedModel === 'none'">
              {{ switchingDeviceModel ? '保存中...' : '保存设备模型' }}
            </button>
            <span class="status-label" style="align-self:flex-end;padding-bottom:10px;">当前来源：{{ deviceModelSource }}</span>
            <span v-if="deviceModelSaveMessage" class="status-label" style="align-self:flex-end;padding-bottom:10px;color:var(--color-success)">{{ deviceModelSaveMessage }}</span>
          </div>

          <div class="device-input-row" style="margin-bottom:0">
            <div class="form-group">
              <label>模型回滚（版本）</label>
              <select class="model-select" v-model="rollbackModelName">
                <option v-for="m in modelCatalog.filter((x) => x.model_name !== 'auto')" :key="m.model_name" :value="m.model_name">{{ m.model_name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>目标版本</label>
              <select class="model-select" v-model="rollbackTargetVersion">
                <option v-for="v in rollbackVersions" :key="v" :value="v">{{ v }}</option>
              </select>
            </div>
            <button class="btn-primary cursor-pointer" @click="doRollbackModel" :disabled="!rollbackTargetVersion || !modelServiceAvailable">执行回滚</button>
          </div>
        </div>

        <div v-if="deviceData" class="card">
          <div class="status-bar">
            <div class="status-item"><span class="status-label">设备</span><span class="status-value">{{ deviceData.dev_num }}</span></div>
            <div class="status-item"><span class="status-label">数据点</span><span class="status-value">{{ deviceData.series.length }}</span></div>
          </div>
          <TrendChart :series="deviceData.series" :marks="deviceData.marks" :show-zoom="true" />
        </div>
      </section>

      <section v-if="page === 'admin'">
        <div class="card">
          <div class="status-bar admin-toolbar">
            <div class="status-item"><span class="status-label">总条数</span><span class="status-value">{{ adminTotal }}</span></div>
            <div class="status-item"><span class="status-label">当前页</span><span class="status-value">第 {{ adminPage }} / {{ adminTotalPages }} 页</span></div>
            <div class="status-item">
              <span class="status-label">状态筛选</span>
              <select class="model-select" v-model="adminStatusFilter">
                <option value="all">全部</option>
                <option value="anomaly">仅异常</option>
                <option value="normal">仅正常</option>
              </select>
            </div>
            <div class="status-item">
              <span class="status-label">排序字段</span>
              <select class="model-select" v-model="adminSortBy">
                <option value="time">按时间</option>
                <option value="score">按分数</option>
              </select>
            </div>
            <div class="status-item">
              <span class="status-label">排序方向</span>
              <select class="model-select" v-model="adminSortOrder">
                <option value="desc">降序</option>
                <option value="asc">升序</option>
              </select>
            </div>
            <div class="status-item">
              <span class="status-label">设备号过滤</span>
              <input class="input admin-search-input" v-model="adminDevKeyword" placeholder="输入设备号关键字" @keyup.enter="searchAdminByDevice" />
            </div>
            <div class="status-item">
              <span class="status-label">每页条数</span>
              <select class="model-select" v-model.number="adminPageSize">
                <option :value="20">20</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
              </select>
            </div>
            <div class="status-item"><span class="status-label">操作</span><button class="btn-primary cursor-pointer" @click="searchAdminByDevice">查询</button></div>
          </div>

          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>设备编号</th>
                  <th>检测时间</th>
                  <th>状态</th>
                  <th>模型</th>
                  <th>分数</th>
                  <th>耗时</th>
                  <th>执行状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in adminRecent" :key="row.request_id + '_' + row.device_timestamp">
                  <td>
                    <button class="table-link cursor-pointer" @click="goToDeviceFromAdmin(row.dev_num)">{{ row.dev_num }}</button>
                  </td>
                  <td>{{ formatTime(row.device_timestamp) }}</td>
                  <td>
                    <span :class="['badge', row.is_anomaly ? 'badge-anomaly' : 'badge-ok']">{{ row.is_anomaly ? '异常' : '正常' }}</span>
                  </td>
                  <td>{{ row.model_name || '--' }}</td>
                  <td>{{ Number(row.anomaly_score || 0).toFixed(4) }}</td>
                  <td>{{ row.infer_latency_ms ?? '--' }}ms</td>
                  <td>{{ row.status || '--' }}</td>
                </tr>
                <tr v-if="!adminRecent.length">
                  <td colspan="7" class="admin-empty">暂无匹配数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="admin-pagination">
            <button class="nav-tab cursor-pointer" :disabled="adminPage <= 1" @click="changeAdminPage(adminPage - 1)">上一页</button>
            <span class="status-label">第 {{ adminPage }} 页 / 共 {{ adminTotalPages }} 页</span>
            <div class="admin-jump-wrap">
              <input class="input admin-jump-input" v-model.number="adminJumpPage" type="number" min="1" :max="adminTotalPages" placeholder="页码" />
              <button class="btn-primary cursor-pointer" @click="goToAdminPage">跳转</button>
            </div>
            <button class="nav-tab cursor-pointer" :disabled="adminPage >= adminTotalPages" @click="changeAdminPage(adminPage + 1)">下一页</button>
          </div>
        </div>
      </section>

      <section v-if="page === 'diag'">
        <div class="card">
          <div class="status-bar">
            <div class="status-item"><span class="status-label">诊断 SSE</span><span class="status-value"><span :class="['badge', diagSseOk ? 'badge-ok' : 'badge-warning']">{{ diagSseOk ? '已连接' : '未连接' }}</span></span></div>
            <div class="status-item"><span class="status-label">实时事件数</span><span class="status-value">{{ diagEvents.length }}</span></div>
            <div class="status-item"><span class="status-label">故障筛选设备</span><input class="input admin-search-input" v-model="diagFaultDevKeyword" placeholder="设备号关键字" /></div>
            <div class="status-item"><span class="status-label">故障时间范围</span><select class="model-select" v-model.number="diagFaultHours"><option :value="0">全部</option><option :value="24">24小时</option><option :value="72">72小时</option><option :value="168">7天</option></select></div>
            <div class="status-item"><span class="status-label">操作</span><button class="btn-primary" @click="loadRecentFaults">刷新故障档案</button></div>
            <div class="status-item"><span class="status-label">导出</span><button class="btn-primary" @click="exportFaultCsv">导出CSV</button></div>
          </div>
          <button class="btn-primary" @click="loadRecentDiag" style="margin-bottom:var(--space-md)">刷新最近流水</button>
        </div>

        <div class="card">
          <h3 class="card-title">检测回放任务</h3>
          <div class="device-input-row">
            <div class="form-group">
              <label>设备编号</label>
              <input class="input" v-model="replayDevNum" placeholder="例如 000000020165453" />
            </div>
            <div class="form-group">
              <label>开始时间戳(ms)</label>
              <input class="input" v-model="replayStartTs" placeholder="例如 1709251200000" />
            </div>
            <div class="form-group">
              <label>结束时间戳(ms)</label>
              <input class="input" v-model="replayEndTs" placeholder="例如 1709337600000" />
            </div>
            <div class="form-group">
              <label>模型</label>
              <select class="model-select" v-model="replayModelName">
                <option value="auto">auto</option>
                <option value="xgboost">xgboost</option>
                <option value="gru">gru</option>
              </select>
            </div>
            <button class="btn-primary" @click="submitReplayTask" :disabled="replaySubmitting">{{ replaySubmitting ? '提交中...' : '提交回放' }}</button>
            <button class="btn-primary" @click="refreshReplayTaskStatus" :disabled="!replayTaskId">刷新任务</button>
          </div>
          <div v-if="replayTaskId" class="json-box">任务ID: {{ replayTaskId }}</div>
          <div v-if="replayTaskStatus" class="json-box">{{ JSON.stringify(replayTaskStatus, null, 2) }}</div>
        </div>

        <div class="card">
          <h3 class="card-title">运行指标</h3>
          <button class="btn-primary" @click="loadRuntimeMetrics" style="margin-bottom:var(--space-md)">刷新指标</button>
          <div v-if="metricsData" class="json-box">{{ JSON.stringify(metricsData, null, 2) }}</div>
          <div v-else class="no-data" style="height:100px">暂无指标</div>
        </div>

        <div v-if="diagEvents.length" class="card">
          <h3 class="card-title">实时诊断推送</h3>
          <div class="event-list">
            <div class="event-row" v-for="(e, i) in diagEvents" :key="i">
              <span>{{ e.dev_num }}</span>
              <span :class="['badge', e.detection?.is_anomaly ? 'badge-anomaly' : 'badge-ok']">{{ e.detection?.is_anomaly ? '异常' : '正常' }}</span>
              <span style="color:var(--color-text-muted)">{{ e.detection?.model_name }} | {{ e.method }} | {{ e.detection?.status }}</span>
              <span style="color:var(--color-text-muted)">异常点: {{ (e.anomaly_points || []).length }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <h3 class="card-title">最近故障档案</h3>
          <div v-if="recentFaults.length" class="event-list" style="max-height:420px;">
            <div class="event-row" v-for="row in recentFaults" :key="row.request_id + '_' + row.device_timestamp">
              <span>{{ row.dev_num }}</span>
              <span>{{ formatTime(row.device_timestamp) }}</span>
              <span :class="['badge', row.is_anomaly ? 'badge-anomaly' : 'badge-ok']">{{ row.is_anomaly ? '异常' : '正常' }}</span>
              <span style="color:var(--color-text-muted)">{{ row.model_name }} | {{ row.method }} | {{ row.diagnosis_status }}</span>
            </div>
          </div>
          <div v-else class="no-data">暂无故障档案数据</div>
        </div>
      </section>
    </main>

    <div v-if="showDeviceIdModal" class="modal-mask" @click.self="showDeviceIdModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>设备ID列表（{{ deviceIds.length }}/{{ deviceIdTotal }}）</h3>
          <button class="nav-tab" @click="showDeviceIdModal = false">关闭</button>
        </div>
        <div class="device-input-row" style="margin-bottom:10px;align-items:flex-end;">
          <div class="form-group">
            <label>设备号搜索</label>
            <input class="input" v-model="deviceIdKeyword" placeholder="输入设备号关键字" @keyup.enter="searchDeviceIds" />
          </div>
          <div class="form-group">
            <label>每页</label>
            <select class="model-select" v-model.number="deviceIdPageSize">
              <option :value="50">50</option>
              <option :value="100">100</option>
              <option :value="200">200</option>
            </select>
          </div>
          <button class="btn-primary cursor-pointer" @click="searchDeviceIds">查询</button>
        </div>
        <div class="event-list" style="max-height: 420px;">
          <div class="event-row">
            <span class="status-label">设备ID</span>
            <span class="status-label">数据条数</span>
          </div>
          <div class="event-row" v-for="item in deviceIds" :key="item.dev_num">
            <span>{{ item.dev_num }}</span>
            <span>{{ item.record_count }}</span>
          </div>
        </div>
        <div class="admin-pagination" style="margin-top:10px;">
          <button class="nav-tab cursor-pointer" :disabled="deviceIdPage <= 1" @click="changeDeviceIdPage(deviceIdPage - 1)">上一页</button>
          <span class="status-label">第 {{ deviceIdPage }} 页 / 共 {{ deviceIdTotalPages }} 页</span>
          <button class="nav-tab cursor-pointer" :disabled="deviceIdPage >= deviceIdTotalPages" @click="changeDeviceIdPage(deviceIdPage + 1)">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import TrendChart from './components/TrendChart.vue'
import {
  createDiagSSE,
  createHomeSSE,
  fetchAdminRecent,
  buildFaultRecentExportUrl,
  fetchFaultRecent,
  fetchDeviceAnomalies,
  fetchDeviceCurve,
  fetchDeviceIds,
  fetchDeviceModel,
  fetchDeviceStats,
  fetchDiagnosisRecent,
  fetchDiagnosisReplayStatus,
  fetchHealth,
  fetchHomeCurrent,
  fetchHomeDeviceTicker,
  fetchModels,
  fetchRuntimeMetrics,
  rollbackModelVersion,
  selectDeviceModel,
  startDiagnosisReplay,
  triggerProcess,
} from './api.js'

const page = ref('home')
const health = ref(null)

const homeDev = ref('')
const homeDetection = ref(null)
const homeRemain = ref(0)
const homeSeries = ref([])
const homeMarks = ref([])
const homeLastUpdateTs = ref(0)
let homeSSE = null
let homeCountdownTimer = null

const triggerDev = ref('000000020165453')
const triggerTs = ref('')
const triggering = ref(false)
const triggerResult = ref(null)

const queryDev = ref('000000020165453')
const queryHours = ref(48)
const querying = ref(false)
const deviceData = ref(null)
const deviceQueryMessage = ref('')

const availableModels = ref([])
const modelServiceAvailable = ref(true)
const modelServiceMessage = ref('')
const deviceSelectedModel = ref('none')
const switchingDeviceModel = ref(false)
const deviceModelSource = ref('default')

const deviceCount = ref(0)
const deviceIds = ref([])
const deviceIdTotal = ref(0)
const showDeviceIdModal = ref(false)
const deviceIdPage = ref(1)
const deviceIdPageSize = ref(100)
const deviceIdKeyword = ref('')
const deviceIdTotalPages = computed(() => Math.max(1, Math.ceil(deviceIdTotal.value / deviceIdPageSize.value)))

const tickerItems = ref([])
const tickerCurrent = ref(null)
let tickerTimer = null

const adminRecent = ref([])
const adminStatusFilter = ref('all')
const adminSortBy = ref('time')
const adminSortOrder = ref('desc')
const adminDevKeyword = ref('')
const adminPage = ref(1)
const adminJumpPage = ref(1)
const adminPageSize = ref(50)
const adminTotal = ref(0)
const adminTotalPages = computed(() => Math.max(1, Math.ceil(adminTotal.value / adminPageSize.value)))
const rollbackVersions = computed(() => {
  const model = modelCatalog.value.find((x) => x.model_name === rollbackModelName.value)
  return model?.versions || []
})
let adminUrlSyncPaused = false

const diagSseOk = ref(false)
const diagEvents = ref([])
const recentDiag = ref([])
const recentFaults = ref([])
const diagFaultDevKeyword = ref('')
const diagFaultHours = ref(0)
const replayDevNum = ref('')
const replayStartTs = ref('')
const replayEndTs = ref('')
const replayModelName = ref('auto')
const replayTaskId = ref('')
const replayTaskStatus = ref(null)
const replaySubmitting = ref(false)
const metricsData = ref(null)
const deviceModelSaveMessage = ref('')
const modelCatalog = ref([])
const rollbackModelName = ref('xgboost')
const rollbackTargetVersion = ref('')
let diagSSE = null

function formatTime(ts) {
  if (!ts) return '--'
  const v = ts > 1e12 ? ts : ts * 1000
  return new Date(v).toLocaleString('zh-CN')
}

function readAdminStateFromUrl() {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  if (view && ['home', 'device', 'admin', 'diag'].includes(view)) page.value = view

  const status = params.get('admin_status')
  if (status && ['all', 'anomaly', 'normal'].includes(status)) adminStatusFilter.value = status

  const sortBy = params.get('admin_sort_by')
  if (sortBy && ['time', 'score'].includes(sortBy)) adminSortBy.value = sortBy

  const sortOrder = params.get('admin_sort_order')
  if (sortOrder && ['asc', 'desc'].includes(sortOrder)) adminSortOrder.value = sortOrder

  const keyword = params.get('admin_dev_num')
  if (keyword !== null) adminDevKeyword.value = keyword

  const pageNo = Number(params.get('admin_page'))
  if (Number.isFinite(pageNo) && pageNo >= 1) adminPage.value = Math.floor(pageNo)

  const pageSize = Number(params.get('admin_page_size'))
  if ([20, 50, 100].includes(pageSize)) adminPageSize.value = pageSize

  const jump = Number(params.get('admin_jump_page'))
  if (Number.isFinite(jump) && jump >= 1) adminJumpPage.value = Math.floor(jump)
}

function syncAdminStateToUrl() {
  if (adminUrlSyncPaused) return
  const params = new URLSearchParams(window.location.search)
  params.set('view', page.value)
  params.set('admin_status', adminStatusFilter.value)
  params.set('admin_sort_by', adminSortBy.value)
  params.set('admin_sort_order', adminSortOrder.value)
  params.set('admin_dev_num', adminDevKeyword.value.trim())
  params.set('admin_page', String(adminPage.value))
  params.set('admin_page_size', String(adminPageSize.value))
  params.set('admin_jump_page', String(adminJumpPage.value || adminPage.value))

  const next = `${window.location.pathname}?${params.toString()}${window.location.hash}`
  window.history.replaceState({}, '', next)
}

async function checkHealth() {
  try {
    const r = await fetchHealth()
    health.value = r.code === 0
  } catch {
    health.value = false
  }
}

async function loadHomeCurrent() {
  try {
    const r = await fetchHomeCurrent()
    if (r.code === 0 && r.data) {
      homeDev.value = r.data.dev_num || ''
      homeDetection.value = r.data.detection
      homeRemain.value = r.data.display_remain_seconds || 0
      homeSeries.value = r.data.series || []
      homeMarks.value = r.data.marks || []
      const latestTs = (r.data.series && r.data.series.length)
        ? (r.data.series[r.data.series.length - 1]?.ts || 0)
        : 0
      homeLastUpdateTs.value = latestTs || r.data.window?.end_ts || 0
    }
  } catch {
    // ignore
  }
}

function startHomeCountdown() {
  if (homeCountdownTimer) clearInterval(homeCountdownTimer)
  homeCountdownTimer = setInterval(() => {
    if (page.value !== 'home') return
    if (homeRemain.value > 0) homeRemain.value -= 1
  }, 1000)
}

function normalizeTickerEvent(raw) {
  if (!raw) return null
  return {
    request_id: raw.request_id,
    dev_num: raw.dev_num,
    device_timestamp: raw.device_timestamp,
    is_anomaly: !!raw.is_anomaly,
    model_name: raw.model_name || '--',
    status: raw.status || '--',
    anomaly_score: raw.anomaly_score,
  }
}

function upsertTickerItems(items = []) {
  const normalized = items
    .map((x) => normalizeTickerEvent(x))
    .filter(Boolean)
    .sort((a, b) => (b.device_timestamp || 0) - (a.device_timestamp || 0))

  tickerItems.value = normalized
  if (!tickerCurrent.value && tickerItems.value.length) tickerCurrent.value = tickerItems.value[0]
}

function appendTickerEvent(raw) {
  const e = normalizeTickerEvent(raw)
  if (!e) return

  const key = `${e.request_id || ''}_${e.dev_num || ''}_${e.device_timestamp || 0}`
  const exists = tickerItems.value.some((x) => `${x.request_id || ''}_${x.dev_num || ''}_${x.device_timestamp || 0}` === key)
  if (exists) return

  tickerItems.value.unshift(e)
  if (tickerItems.value.length > 200) tickerItems.value.length = 200
  if (!tickerCurrent.value) tickerCurrent.value = e
}

function connectHomeSSE() {
  if (homeSSE) homeSSE.close()
  homeSSE = createHomeSSE()
  homeSSE.addEventListener('device_update', () => loadHomeCurrent())
  homeSSE.addEventListener('device_switch', () => loadHomeCurrent())
  homeSSE.addEventListener('anomaly_mark', () => loadHomeCurrent())
  homeSSE.addEventListener('ticker_event', (evt) => {
    try {
      const payload = JSON.parse(evt.data)
      appendTickerEvent(payload)
    } catch {
      // ignore malformed ticker event
    }
  })
}

function connectDiagSSE() {
  if (diagSSE) diagSSE.close()
  diagSSE = createDiagSSE()
  diagSSE.onopen = () => {
    diagSseOk.value = true
  }
  diagSSE.onerror = () => {
    diagSseOk.value = false
  }
  diagSSE.addEventListener('diagnosis_result', (e) => {
    try {
      const data = JSON.parse(e.data)
      diagEvents.value.unshift(data)
      if (diagEvents.value.length > 100) diagEvents.value.length = 100
    } catch {
      // ignore
    }
  })
}

async function doTrigger() {
  triggering.value = true
  triggerResult.value = null
  try {
    const r = await triggerProcess(triggerDev.value.trim(), parseInt(triggerTs.value) || Date.now())
    triggerResult.value = r
    await Promise.all([loadHomeCurrent(), loadHomeTicker(), loadAdminRecent()])
  } catch (err) {
    triggerResult.value = { error: err.message }
  } finally {
    triggering.value = false
  }
}

async function doQueryDevice(custom = {}) {
  querying.value = true
  deviceQueryMessage.value = ''
  try {
    const dev = queryDev.value.trim()
    if (!dev) {
      deviceData.value = null
      deviceQueryMessage.value = '请输入设备编号'
      return
    }

    // 查询前按当前选择处理模型：none=仅查询；其他=先尝试切换模型再查询
    if (!modelServiceAvailable.value && deviceSelectedModel.value !== 'none') {
      deviceSelectedModel.value = 'none'
      deviceModelSource.value = 'none'
      deviceData.value = null
      deviceQueryMessage.value = modelServiceMessage.value || '模型服务不可用，已切换为 none 仅查询模式'
      return
    } else if (modelServiceAvailable.value && deviceSelectedModel.value !== 'none') {
      const saveRes = await selectDeviceModel(dev, deviceSelectedModel.value)
      if (saveRes.code !== 0) {
        deviceData.value = null
        deviceQueryMessage.value = saveRes.message || '模型保存失败，请重试'
        return
      }
      deviceModelSource.value = 'device'
      deviceQueryMessage.value = `已切换设备模型为 ${deviceSelectedModel.value}，正在查询数据`
    }

    let hours = Number(queryHours.value) || 48
    hours = Math.min(Math.max(1, hours), 8760)
    queryHours.value = hours

    const endTs = custom?.endTs || null
    const pointsLimit = custom?.pointsLimit || null
    let curveRes = await fetchDeviceCurve(dev, hours, endTs, pointsLimit)
    if (curveRes.code !== 0 && curveRes.message && curveRes.message.includes('no data') && hours < 8760) {
      curveRes = await fetchDeviceCurve(dev, 8760, null, pointsLimit)
      if (curveRes.code === 0) {
        queryHours.value = 8760
        deviceQueryMessage.value = '当前小时范围无数据，已自动扩展到最近一年'
      }
    }

    if (curveRes.code === 0) {
      deviceData.value = curveRes.data
      const anomalyRes = await fetchDeviceAnomalies(dev, queryHours.value)
      if (anomalyRes.code === 0 && deviceData.value) {
        deviceData.value.marks = anomalyRes.data.items || []
      }
    } else {
      deviceData.value = null
      deviceQueryMessage.value = curveRes.message || '查询失败，请检查设备号和时间范围'
    }

  } catch (err) {
    deviceData.value = null
    deviceQueryMessage.value = err?.message || '查询异常，请稍后重试'
  } finally {
    querying.value = false
  }
}

async function loadModels() {
  try {
    const r = await fetchModels()
    if (r.code === 0) {
      const modelEnabled = !!r.data?.model_service_enabled
      modelServiceAvailable.value = modelEnabled
      modelServiceMessage.value = modelEnabled ? '' : '当前未提供 xgboost/gru 模型，模型切换已禁用，仅支持 none 查询模式'
      const models = r.data?.models || []
      availableModels.value = models.filter((m) => m.enabled)
      modelCatalog.value = models

      if (!modelEnabled) {
        deviceSelectedModel.value = 'none'
        deviceModelSource.value = 'none'
      }

      const firstRollbackModel = models.find((m) => m.model_name !== 'auto')
      if (firstRollbackModel) {
        rollbackModelName.value = firstRollbackModel.model_name
        rollbackTargetVersion.value = firstRollbackModel.active_version || firstRollbackModel.latest_version || ''
      }
      return
    }

    modelServiceAvailable.value = false
    modelServiceMessage.value = r.message || '模型服务暂不可用，当前仅支持 none 查询模式'
    availableModels.value = []
    modelCatalog.value = []
    deviceSelectedModel.value = 'none'
  } catch (err) {
    modelServiceAvailable.value = false
    modelServiceMessage.value = err?.message || '模型服务暂不可用，当前仅支持 none 查询模式'
    availableModels.value = []
    modelCatalog.value = []
    deviceSelectedModel.value = 'none'
  }
}

async function loadDeviceModel(devNum, keepNoneSelection = false) {
  if (!devNum) return
  if (!modelServiceAvailable.value) {
    deviceSelectedModel.value = 'none'
    deviceModelSource.value = 'none'
    return
  }
  const r = await fetchDeviceModel(devNum)
  if (r.code === 0 && r.data) {
    if (!(keepNoneSelection && deviceSelectedModel.value === 'none')) {
      deviceSelectedModel.value = r.data.model_name
    }
    deviceModelSource.value = r.data.source
  }
}

async function saveDeviceModel() {
  const dev = queryDev.value.trim()
  if (!dev) return
  if (deviceSelectedModel.value === 'none') {
    deviceModelSaveMessage.value = '当前为 none，仅查询数据，不保存模型'
    setTimeout(() => {
      deviceModelSaveMessage.value = ''
    }, 2500)
    return
  }
  switchingDeviceModel.value = true
  deviceModelSaveMessage.value = ''
  try {
    const r = await selectDeviceModel(dev, deviceSelectedModel.value)
    if (r.code === 0) {
      await loadDeviceModel(dev)
      deviceModelSaveMessage.value = '设备模型已保存'
      setTimeout(() => {
        deviceModelSaveMessage.value = ''
      }, 2500)
    }
  } finally {
    switchingDeviceModel.value = false
  }
}

async function loadDeviceStatsAndIds() {
  const [statsRes, idsRes] = await Promise.all([
    fetchDeviceStats(),
    fetchDeviceIds(deviceIdPage.value, deviceIdPageSize.value, 'count', 'desc', deviceIdKeyword.value.trim()),
  ])
  if (statsRes.code === 0) deviceCount.value = statsRes.data.device_count || 0
  if (idsRes.code === 0) {
    deviceIds.value = idsRes.data.items || []
    deviceIdTotal.value = idsRes.data.total || 0
    deviceIdPage.value = idsRes.data.page || deviceIdPage.value
    deviceIdPageSize.value = idsRes.data.page_size || deviceIdPageSize.value
  }
}

async function loadHomeTicker() {
  const r = await fetchHomeDeviceTicker(50)
  if (r.code === 0) {
    upsertTickerItems(r.data.items || [])
  }
}

function startTicker() {
  if (tickerTimer) clearInterval(tickerTimer)
  tickerTimer = setInterval(() => {
    if (!tickerItems.value.length) return

    const currentTs = tickerCurrent.value?.device_timestamp
    const currentReq = tickerCurrent.value?.request_id
    let idx = tickerItems.value.findIndex((x) => x.device_timestamp === currentTs && x.request_id === currentReq)

    if (idx < 0) idx = 0
    else idx = (idx + 1) % tickerItems.value.length

    tickerCurrent.value = tickerItems.value[idx]
  }, 2500)
}

async function loadAdminRecent() {
  const r = await fetchAdminRecent(
    adminPage.value,
    adminPageSize.value,
    adminStatusFilter.value,
    adminSortBy.value,
    adminSortOrder.value,
    adminDevKeyword.value.trim(),
  )
  if (r.code === 0) {
    adminRecent.value = r.data.items || []
    adminTotal.value = r.data.total || 0
    adminPage.value = r.data.page || adminPage.value
    adminPageSize.value = r.data.page_size || adminPageSize.value
  }
}

function changeAdminPage(nextPage) {
  const safePage = Math.min(Math.max(1, nextPage), adminTotalPages.value)
  if (safePage === adminPage.value) return
  adminPage.value = safePage
  adminJumpPage.value = safePage
  loadAdminRecent()
}

function goToAdminPage() {
  const target = Number(adminJumpPage.value)
  if (!Number.isFinite(target)) return
  changeAdminPage(Math.floor(target))
}

function changeDeviceIdPage(nextPage) {
  const safePage = Math.min(Math.max(1, nextPage), deviceIdTotalPages.value)
  if (safePage === deviceIdPage.value) return
  deviceIdPage.value = safePage
  loadDeviceStatsAndIds()
}

async function searchDeviceIds() {
  deviceIdPage.value = 1
  await loadDeviceStatsAndIds()
}

async function searchAdminByDevice() {
  adminPage.value = 1
  await loadAdminRecent()
}

async function loadRecentDiag() {
  const r = await fetchDiagnosisRecent(200)
  if (r.code === 0) recentDiag.value = r.data.items || []
}

async function submitReplayTask() {
  const dev = replayDevNum.value.trim()
  const startTs = Number(replayStartTs.value)
  const endTs = Number(replayEndTs.value)
  if (!dev || !Number.isFinite(startTs) || !Number.isFinite(endTs)) {
    deviceQueryMessage.value = '回放任务参数不完整，请检查设备号和时间戳'
    return
  }
  replaySubmitting.value = true
  try {
    const r = await startDiagnosisReplay(dev, startTs, endTs, replayModelName.value)
    if (r.code === 0 && r.data?.task_id) {
      replayTaskId.value = r.data.task_id
      await refreshReplayTaskStatus()
    } else {
      deviceQueryMessage.value = r.message || '提交回放任务失败'
    }
  } finally {
    replaySubmitting.value = false
  }
}

async function refreshReplayTaskStatus() {
  if (!replayTaskId.value) return
  const r = await fetchDiagnosisReplayStatus(replayTaskId.value)
  if (r.code === 0) replayTaskStatus.value = r.data
}

async function loadRuntimeMetrics() {
  const r = await fetchRuntimeMetrics()
  if (r.code === 0) metricsData.value = r.data
}

async function loadRecentFaults() {
  const r = await fetchFaultRecent(100, diagFaultDevKeyword.value.trim(), diagFaultHours.value)
  if (r.code === 0) recentFaults.value = r.data.items || []
}

function exportFaultCsv() {
  const url = buildFaultRecentExportUrl(2000, diagFaultDevKeyword.value.trim(), diagFaultHours.value)
  window.open(url, '_blank')
}

async function doRollbackModel() {
  if (!rollbackTargetVersion.value) return
  if (!modelServiceAvailable.value) {
    deviceModelSaveMessage.value = '模型服务不可用，暂无法回滚版本'
    setTimeout(() => {
      deviceModelSaveMessage.value = ''
    }, 2500)
    return
  }
  const r = await rollbackModelVersion(rollbackModelName.value, rollbackTargetVersion.value)
  if (r.code === 0) {
    deviceModelSaveMessage.value = '模型版本回滚成功'
    setTimeout(() => {
      deviceModelSaveMessage.value = ''
    }, 2500)
    await loadModels()
  }
}

function goToDeviceFromAdmin(devNum) {
  queryDev.value = devNum
  page.value = 'device'
  doQueryDevice()
}

function goToDeviceFromTicker(item) {
  const v = (item?.dev_num || '').trim()
  if (!v) return
  queryDev.value = v
  page.value = 'device'

  // 从轮播跳转时，按“最近N点 + 事件锚点”查询，尽量与首页实时图视觉一致
  const anchorTs = item?.device_timestamp || null
  queryHours.value = 2
  doQueryDevice({ endTs: anchorTs, pointsLimit: 120 })
}

watch(showDeviceIdModal, async (v) => {
  if (v) await loadDeviceStatsAndIds()
})

watch([deviceSelectedModel, modelServiceAvailable], ([selected, available]) => {
  if (!available && selected !== 'none') {
    deviceSelectedModel.value = 'none'
    return
  }
  if (selected === 'none') {
    deviceModelSource.value = 'none'
  }
})

watch([adminStatusFilter, adminPageSize, adminSortBy, adminSortOrder], async () => {
  adminPage.value = 1
  syncAdminStateToUrl()
  await loadAdminRecent()
})

watch([page, adminPage, adminJumpPage, adminPageSize, adminStatusFilter, adminSortBy, adminSortOrder, adminDevKeyword], () => {
  syncAdminStateToUrl()
})

onMounted(async () => {
  adminUrlSyncPaused = true
  readAdminStateFromUrl()
  adminUrlSyncPaused = false
  syncAdminStateToUrl()

  await Promise.all([
    checkHealth(),
    loadModels(),
    loadHomeCurrent(),
    loadHomeTicker(),
    loadDeviceStatsAndIds(),
    loadAdminRecent(),
    loadRecentDiag(),
    loadRecentFaults(),
  ])
  connectHomeSSE()
  connectDiagSSE()
  startTicker()
  startHomeCountdown()
})

onUnmounted(() => {
  if (homeSSE) homeSSE.close()
  if (diagSSE) diagSSE.close()
  if (tickerTimer) clearInterval(tickerTimer)
  if (homeCountdownTimer) clearInterval(homeCountdownTimer)
})
</script>