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
                    <span v-if="homeDetection" :class="['badge', triStateBadgeClass(homeDetection)]">
                      {{ triStateLabel(homeDetection) }}
                    </span>
                    <span v-else class="badge badge-muted">--</span>
                  </span>
                </div>
                <div class="status-item">
                  <span class="status-label">模型（首页固定）</span>
                  <span class="status-value">{{ homeDetection?.model_name || 'auto' }}</span>
                </div>
                <div class="status-item">
                  <span class="status-label">异常类型</span>
                  <span class="status-value">{{ homeDetection?.status_label || homeDetection?.status || '--' }}</span>
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
              <div class="device-input-row" style="margin-top:12px;margin-bottom:0;">
                <div class="form-group">
                  <label>首页默认模型</label>
                  <select class="model-select" v-model="homeSelectedModel">
                    <option
                      v-for="m in modelCatalog"
                      :key="`home_${m.model_name}`"
                      :value="m.model_name"
                      :disabled="!m.enabled"
                    >
                      {{ m.model_name }}{{ m.enabled ? '' : '（未提供）' }}
                    </option>
                  </select>
                </div>
                <button
                  class="btn-primary cursor-pointer"
                  @click="saveHomeModel"
                  :disabled="switchingHomeModel || !isModelEnabled(homeSelectedModel)"
                >
                  {{ switchingHomeModel ? '保存中...' : '切换首页模型' }}
                </button>
                <span class="status-label" style="align-self:flex-end;padding-bottom:10px;">
                  当前默认：{{ homeSelectedModel }} / 实际生效：{{ homeEffectiveModel }}
                </span>
                <span
                  v-if="homeModelMessage"
                  class="status-label"
                  style="align-self:flex-end;padding-bottom:10px;color:var(--color-success)"
                >
                  {{ homeModelMessage }}
                </span>
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
                <div class="ticker-current" :class="{ anomaly: triStateTone(tickerCurrent) === 'danger' }">
                  <div class="ticker-dev table-link cursor-pointer" @click="goToDeviceFromTicker(tickerCurrent)">{{ tickerCurrent?.dev_num }}</div>
                  <div class="ticker-meta">
                    <span :class="['badge', triStateBadgeClass(tickerCurrent)]">
                      {{ triStateLabel(tickerCurrent) }}
                    </span>
                    <span class="ticker-time">{{ formatTime(tickerCurrent?.device_timestamp) }}</span>
                  </div>
                  <div class="ticker-sub">{{ tickerCurrent?.model_name }} | {{ tickerCurrent?.status_label || tickerCurrent?.status }}</div>
                </div>

                <div class="ticker-list">
                  <div class="ticker-row" v-for="(item, idx) in tickerItems.slice(0, 12)" :key="item.dev_num + '_' + idx">
                    <button class="ticker-row-dev table-link cursor-pointer" @click="goToDeviceFromTicker(item)">{{ item.dev_num }}</button>
                    <span :class="['badge', triStateBadgeClass(item)]">
                      {{ triStateLabel(item) }}
                    </span>
                    <span class="status-label" style="margin-left:8px;">{{ item.status_short || item.status_label || item.status }}</span>
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

          <div v-if="modelServiceMessage || deviceSelectedModel === 'none'" class="status-label" style="color:var(--color-warning);margin-bottom:10px;">
            {{ deviceSelectedModel === 'none' ? '当前为 none 模式：仅查询数据，不切换模型' : modelServiceMessage }}
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
            <button class="btn-primary cursor-pointer" @click="saveDeviceModel" :disabled="switchingDeviceModel || !queryDev.trim() || deviceSelectedModel === 'none' || !selectedDeviceModelEnabled">
              {{ switchingDeviceModel ? '保存中...' : '保存设备模型' }}
            </button>
            <span class="status-label" style="align-self:flex-end;padding-bottom:10px;">当前来源：{{ deviceModelSource }}</span>
            <span v-if="deviceModelSaveMessage" class="status-label" style="align-self:flex-end;padding-bottom:10px;color:var(--color-success)">{{ deviceModelSaveMessage }}</span>
          </div>

          <div class="device-input-row" style="margin-bottom:0">
            <div class="form-group">
              <label>模型回滚（版本）</label>
              <select class="model-select" v-model="rollbackModelName">
                <option v-for="m in rollbackModelCatalog" :key="m.model_name" :value="m.model_name">{{ m.model_name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>目标版本</label>
              <select class="model-select" v-model="rollbackTargetVersion">
                <option v-for="v in rollbackVersions" :key="v" :value="v">{{ v }}</option>
              </select>
            </div>
            <button class="btn-primary cursor-pointer" @click="doRollbackModel" :disabled="!rollbackTargetVersion || !rollbackModelCatalog.length">执行回滚</button>
          </div>
        </div>

        <div class="card">
          <h3 class="card-title">模型对比回放（只读，不落库）</h3>
          <div class="device-input-row">
            <div class="form-group">
              <label>对比小时数</label>
              <input class="input" v-model.number="compareHours" type="number" min="1" max="8760" />
            </div>
            <div class="form-group">
              <label>区间来源</label>
              <select class="model-select" v-model="compareRangeMode">
                <option value="hours">按对比小时数</option>
                <option value="current">使用当前查询区间</option>
              </select>
            </div>
            <div class="form-group">
              <label>最大扫描点</label>
              <input class="input" v-model.number="compareMaxScanPoints" type="number" min="20" max="300" />
            </div>
            <button class="btn-primary cursor-pointer" @click="runDeviceModelCompare" :disabled="comparingModels || !queryDev.trim()">
              {{ comparingModels ? '对比中...' : '执行模型对比' }}
            </button>
          </div>
          <div class="status-label" style="margin-top:-8px;margin-bottom:8px;color:var(--color-text-muted);">
            建议默认按“对比小时数”做模型评估；若要对齐当前曲线视图，可切换为“使用当前查询区间”。结果仅用于分析，不写入实时检测与故障档案，仅记录在模型响应日志中。
          </div>
          <div class="device-input-row" style="gap:14px;flex-wrap:wrap;margin-bottom:6px;">
            <label
              v-for="m in compareModelOptions"
              :key="`cmp_${m.model_name}`"
              class="status-label"
              style="display:flex;align-items:center;gap:6px;padding-bottom:0;cursor:pointer;"
            >
              <input
                type="checkbox"
                :checked="compareSelectedModels.includes(m.model_name)"
                @change="toggleCompareModel(m.model_name, $event.target.checked)"
              />
              <span>{{ m.model_name }}</span>
            </label>
          </div>
          <div v-if="deviceModelCompareMessage" class="status-label" style="color:var(--color-warning);margin-top:4px;">
            {{ deviceModelCompareMessage }}
          </div>
          <div v-if="deviceModelCompareResult?.results?.length" class="device-input-row" style="margin-top:8px;margin-bottom:0;">
            <div class="form-group">
              <label>图表预览模型</label>
              <select class="model-select" v-model="comparePreviewModelName">
                <option value="">实时结果（默认）</option>
                <option v-for="row in comparePreviewOptions" :key="`cmp_preview_${row.model_name}`" :value="row.model_name">
                  {{ row.model_name }}
                </option>
              </select>
            </div>
            <button class="nav-tab cursor-pointer" @click="clearComparePreview">恢复实时结果</button>
          </div>
          <div v-if="deviceModelCompareResult?.results?.length" class="admin-table-wrap" style="margin-top:10px;">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>扫描点</th>
                  <th>异常点</th>
                  <th>异常标记</th>
                  <th>最新状态</th>
                  <th>最新分数</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in deviceModelCompareResult.results"
                  :key="`cmp_row_${row.model_name}`"
                  :style="comparePreviewModelName === row.model_name ? 'background: rgba(34,197,94,0.08);' : ''"
                >
                  <td>{{ row.model_name }} / {{ row.effective_model_name }}</td>
                  <td>{{ row.summary?.scan_count ?? '--' }}</td>
                  <td>{{ row.summary?.anomaly_count ?? '--' }}</td>
                  <td>{{ row.summary?.mark_count ?? '--' }}</td>
                  <td>{{ row.latest_detection?.status_label || row.latest_detection?.status || row.skip_reason || '--' }}</td>
                  <td>{{ row.latest_detection?.anomaly_score != null ? Number(row.latest_detection.anomaly_score).toFixed(4) : '--' }}</td>
                  <td>{{ row.summary?.elapsed_ms ?? '--' }}ms</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="deviceData" class="card">
          <div class="status-bar">
            <div class="status-item"><span class="status-label">设备</span><span class="status-value">{{ deviceData.dev_num }}</span></div>
            <div class="status-item"><span class="status-label">数据点</span><span class="status-value">{{ deviceData.series.length }}</span></div>
            <div class="status-item">
              <span class="status-label">数据来源</span>
              <span class="status-value">
                <span v-if="deviceData?.range?.source === 'upload_xlsx'" class="badge badge-warning">实验室调试模式</span>
                <span v-else class="badge badge-muted">数据库查询</span>
              </span>
            </div>
            <div v-if="deviceData?.range?.file_name" class="status-item">
              <span class="status-label">文件</span>
              <span class="status-value">{{ deviceData.range.file_name }}</span>
            </div>
            <div v-if="deviceData?.range?.scan_points" class="status-item">
              <span class="status-label">扫描窗口</span>
              <span class="status-value">{{ deviceData.range.scan_points }}</span>
            </div>
            <div v-if="deviceData?.scan_summary?.abnormal_window_count > 0" class="status-item">
              <span class="status-label">异常窗口</span>
              <span class="status-value">{{ deviceData.scan_summary.abnormal_window_count }} / {{ deviceData.scan_summary.window_count }}</span>
            </div>
            <div v-else-if="deviceData?.scan_summary?.window_count" class="status-item">
              <span class="status-label">异常窗口</span>
              <span class="status-value">0 / {{ deviceData.scan_summary.window_count }}</span>
            </div>
            <div v-if="uploadResult?.data?.summary?.elapsed_ms" class="status-item">
              <span class="status-label">分析耗时</span>
              <span class="status-value">{{ uploadResult.data.summary.elapsed_ms }} ms</span>
            </div>
            <div v-if="deviceChartMarks?.length" class="status-item">
              <span class="status-label">图中标记</span>
              <span class="status-value">{{ deviceChartMarks.length }}</span>
            </div>
            <div class="status-item">
              <span class="status-label">最新检测</span>
              <span class="status-value">
                <span
                  v-if="deviceData?.latest_detection"
                  :class="['badge', triStateBadgeClass(deviceData.latest_detection)]"
                >
                  {{ triStateLabel(deviceData.latest_detection) }}
                </span>
                <span v-else class="badge badge-muted">--</span>
              </span>
            </div>
            <div v-if="deviceData?.latest_detection?.status_label" class="status-item">
              <span class="status-label">最新状态</span>
              <span class="status-value">{{ deviceData.latest_detection.status_label }}</span>
            </div>
            <div v-if="deviceData?.latest_detection?.label" class="status-item">
              <span class="status-label">原始标签</span>
              <span class="status-value">{{ deviceData.latest_detection.label }}</span>
            </div>
            <div v-if="deviceData?.latest_detection?.condition" class="status-item">
              <span class="status-label">路由工况</span>
              <span class="status-value">{{ deviceData.latest_detection.condition }}</span>
            </div>
            <div v-if="deviceData?.latest_detection?.routed_model" class="status-item">
              <span class="status-label">子模型</span>
              <span class="status-value">{{ deviceData.latest_detection.routed_model }}</span>
            </div>
            <div v-if="deviceData?.latest_detection?.error_detail" class="status-item" style="min-width:320px;">
              <span class="status-label">异常原因</span>
              <span class="status-value" style="white-space:normal;word-break:break-word;">{{ deviceData.latest_detection.error_detail }}</span>
            </div>
            <div v-if="deviceData?.scan_summary?.first_abnormal_window_ts" class="status-item">
              <span class="status-label">首个异常窗</span>
              <span class="status-value">{{ formatTime(deviceData.scan_summary.first_abnormal_window_ts) }}</span>
            </div>
            <div v-if="deviceData?.scan_summary?.last_abnormal_window_ts" class="status-item">
              <span class="status-label">最后异常窗</span>
              <span class="status-value">{{ formatTime(deviceData.scan_summary.last_abnormal_window_ts) }}</span>
            </div>
            <div v-if="deviceTransitionEvent" class="status-item">
              <span class="status-label">转移事件</span>
              <span class="status-value">{{ formatTime(deviceTransitionEvent.event_start_ts) }} -> {{ formatTime(deviceTransitionEvent.peak_time_ts) }} -> {{ formatTime(deviceTransitionEvent.event_end_ts) }}</span>
            </div>
          </div>
          <TrendChart :series="deviceData.series" :marks="deviceChartMarks" :show-zoom="true" />
          <div class="status-label" style="margin-top:10px;color:var(--color-text-muted);">
            {{ deviceChartMarkSourceText }}
          </div>
          <div v-if="deviceChartMarks?.length > 10" class="status-label" style="margin-top:10px;color:var(--color-text-muted);">
            图中仅保留最近少量关键标注，完整异常时间请以下方摘要和悬浮提示为准。
          </div>
          <div v-if="deviceScanSummaryText" class="status-label" style="margin-top:10px;color:var(--color-text-muted);">
            {{ deviceScanSummaryText }}
          </div>
          <div v-if="deviceMarkPreview.length" class="mark-chip-panel">
            <div class="status-label">图中标记摘要（最近 {{ deviceMarkPreview.length }} 条）</div>
            <div class="mark-chip-list">
              <div v-for="item in deviceMarkPreview" :key="`${item.display_mark_ts}_${item.status}`" class="mark-chip">
                <span :class="['badge', badgeClassByTone(item)]">{{ item.status_short || item.status_label || item.status || '标记' }}</span>
                <span class="mark-chip-time">{{ formatTime(item.display_mark_ts) }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="page === 'admin'">
        <div class="card">
          <h3 class="card-title">模型响应分析（模型评估）</h3>
          <div class="status-bar admin-toolbar">
            <div class="status-item">
              <span class="status-label">来源</span>
              <select class="model-select" v-model="analysisSource">
                <option value="all">全部</option>
                <option value="online">实时</option>
                <option value="replay">回放</option>
                <option value="compare">对比</option>
                <option value="upload">上传</option>
              </select>
            </div>
            <div class="status-item">
              <span class="status-label">统计小时</span>
              <input class="input admin-jump-input" v-model.number="analysisHours" type="number" min="1" max="8760" />
            </div>
            <div class="status-item">
              <span class="status-label">设备号过滤</span>
              <input class="input admin-search-input" v-model="analysisDevKeyword" placeholder="可选设备号关键字" />
            </div>
            <div class="status-item">
              <span class="status-label">操作</span>
              <button class="btn-primary cursor-pointer" :disabled="analysisLoading" @click="loadModelResponseInsights">
                {{ analysisLoading ? '加载中...' : '刷新分析' }}
              </button>
            </div>
          </div>
          <div class="status-label" style="margin-top:-8px;margin-bottom:10px;color:var(--color-text-muted);">
            汇总展示所有响应；下方明细默认仅展示异常响应，便于快速做模型效果复盘。
          </div>
          <div v-if="analysisMessage" class="status-label" style="margin-top:-8px;margin-bottom:10px;color:var(--color-warning);">
            {{ analysisMessage }}
          </div>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>总响应</th>
                  <th>异常数</th>
                  <th>异常率</th>
                  <th>平均分</th>
                  <th>最高分</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in analysisSummaryRows" :key="`analysis_summary_${row.model_name}`">
                  <td>{{ row.model_name || '--' }}</td>
                  <td>{{ row.total_count ?? 0 }}</td>
                  <td>{{ row.anomaly_count ?? 0 }}</td>
                  <td>{{ Number(row.anomaly_rate || 0).toFixed(2) }}%</td>
                  <td>{{ row.avg_score != null ? Number(row.avg_score).toFixed(4) : '--' }}</td>
                  <td>{{ row.max_score != null ? Number(row.max_score).toFixed(4) : '--' }}</td>
                </tr>
                <tr v-if="!analysisSummaryRows.length">
                  <td colspan="6" class="admin-empty">暂无模型响应汇总数据</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="admin-table-wrap" style="margin-top:10px;">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>检测时间</th>
                  <th>设备</th>
                  <th>来源</th>
                  <th>请求模型</th>
                  <th>状态</th>
                  <th>分数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in analysisRecentAnomalies" :key="`analysis_recent_${row.run_id}_${row.dev_num}_${row.device_timestamp}`">
                  <td>{{ formatTime(row.device_timestamp) }}</td>
                  <td>{{ row.dev_num }}</td>
                  <td>{{ row.source || '--' }}</td>
                  <td>{{ row.requested_model_name || '--' }}</td>
                  <td>
                    <button class="status-text-btn cursor-pointer" @click="openAnomalyDetail(row, 'analysis_recent')">
                      {{ row.status_label || row.status || '--' }}
                    </button>
                  </td>
                  <td>{{ row.anomaly_score != null ? Number(row.anomaly_score).toFixed(4) : '--' }}</td>
                </tr>
                <tr v-if="!analysisRecentAnomalies.length">
                  <td colspan="6" class="admin-empty">暂无异常响应明细</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

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
          <div class="status-label" style="margin-top:-8px;margin-bottom:10px;color:var(--color-text-muted);">
            点击“状态”或“执行状态”可查看该条电机异常的详细解释与排查建议。
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
                    <button class="status-chip-btn cursor-pointer" @click="openAnomalyDetail(row, 'admin_recent')">
                      <span :class="['badge', triStateBadgeClass(row)]">{{ triStateLabel(row) }}</span>
                    </button>
                  </td>
                  <td>{{ row.model_name || '--' }}</td>
                  <td>{{ Number(row.anomaly_score || 0).toFixed(4) }}</td>
                  <td>{{ row.infer_latency_ms ?? '--' }}ms</td>
                  <td>
                    <button class="status-text-btn cursor-pointer" @click="openAnomalyDetail(row, 'admin_recent')">
                      {{ row.status_label || row.status || '--' }}
                    </button>
                  </td>
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
                <option value="seal_v4">seal_v4</option>
                <option value="salad_gru" :disabled="!isModelEnabled('salad_gru')">salad_gru</option>
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
          <h3 class="card-title">本地 Excel 上传检测</h3>
          <div class="device-input-row">
            <div class="form-group">
              <label>Excel 文件</label>
              <input class="input" type="file" accept=".xlsx,.xls" @change="onUploadFileChange" />
            </div>
            <div class="form-group">
              <label>模型</label>
              <select class="model-select" v-model="uploadModelName">
                <option value="seal_v4">seal_v4</option>
                <option value="auto">auto</option>
                <option value="salad_gru" :disabled="!isModelEnabled('salad_gru')">salad_gru</option>
                <option value="xgboost" :disabled="!isModelEnabled('xgboost')">xgboost</option>
                <option value="gru" :disabled="!isModelEnabled('gru')">gru</option>
              </select>
            </div>
            <div class="form-group">
              <label>设备号提示（可选）</label>
              <input class="input" v-model="uploadDevHint" placeholder="例如 demo_a312" />
            </div>
            <div class="form-group">
              <label>处理模式</label>
              <select class="model-select" v-model="uploadProcessMode">
                <option value="full">full（整文件回放）</option>
                <option value="latest">latest（仅最后一点）</option>
              </select>
            </div>
            <button class="btn-primary" @click="submitUploadXlsx" :disabled="uploadingXlsx || !uploadFile">
              {{ uploadingXlsx ? '上传处理中...' : '上传并检测' }}
            </button>
          </div>
          <div v-if="uploadMessage" class="status-label" style="color:var(--color-warning);margin-top:-8px;margin-bottom:12px;">{{ uploadMessage }}</div>
          <div v-if="uploadResult" class="json-box">{{ JSON.stringify(uploadResult, null, 2) }}</div>
        </div>

        <div class="card">
          <h3 class="card-title">新数据复核收口执行</h3>
          <div class="device-input-row">
            <div class="form-group">
              <label>说明 Excel</label>
              <input class="input" v-model="reviewFinalizeReadmeXlsx" placeholder="/Users/xpker/Downloads/data_readme.xlsx" />
            </div>
            <div class="form-group">
              <label>段清单 CSV</label>
              <input class="input" v-model="reviewFinalizeManifestCsv" placeholder="reports/.../segment_pipeline_manifest.csv" />
            </div>
            <div class="form-group">
              <label>支撑结果 CSV</label>
              <input class="input" v-model="reviewFinalizeSupportCsv" placeholder="reports/.../segment_support_output_v3.csv" />
            </div>
          </div>
          <div class="device-input-row">
            <div class="form-group">
              <label>复核队列 CSV</label>
              <input class="input" v-model="reviewFinalizeQueueCsv" placeholder="reports/.../segment_review_queue_v3.csv" />
            </div>
            <div class="form-group">
              <label>工作标签 CSV</label>
              <input class="input" v-model="reviewFinalizeLabelsCsv" placeholder="reports/.../segment_review_labels_working_v2.csv" />
            </div>
            <div class="form-group">
              <label>自动种子 CSV</label>
              <input class="input" v-model="reviewFinalizeAutoSeedCsv" placeholder="reports/.../segment_review_labels_auto_seed_v2.csv" />
            </div>
          </div>
          <div class="device-input-row">
            <div class="form-group" style="flex:1 1 520px;">
              <label>输出目录</label>
              <input class="input" v-model="reviewFinalizeOutputDir" placeholder="reports/new_data_review_finalize_v1_run1" />
            </div>
            <button class="btn-primary" @click="loadReviewFinalizeDefaults" :disabled="reviewFinalizeSubmitting">
              载入默认路径
            </button>
            <button class="btn-primary" @click="submitReviewFinalize" :disabled="reviewFinalizeSubmitting">
              {{ reviewFinalizeSubmitting ? '执行中...' : '执行复核收口' }}
            </button>
          </div>
          <div v-if="reviewFinalizeFileStatus.length" class="event-list" style="margin-top:-4px;margin-bottom:12px;">
            <div class="event-row" v-for="item in reviewFinalizeFileStatus" :key="item.key">
              <span>{{ item.label }}</span>
              <span :class="['badge', item.exists ? 'badge-ok' : 'badge-warning']">{{ item.exists ? '已找到' : '未找到' }}</span>
              <span style="color:var(--color-text-muted)">{{ item.path }}</span>
            </div>
          </div>
          <div class="status-label" style="margin-top:-8px;margin-bottom:12px;color:var(--color-text-muted);">
            作用：读取人工编辑后的 `segment_review_labels_working_v2.csv`，自动回灌并刷新 pending 与调优建议。
          </div>
          <div v-if="reviewFinalizeMessage" class="status-label" style="color:var(--color-warning);margin-top:-8px;margin-bottom:12px;">{{ reviewFinalizeMessage }}</div>
          <div v-if="reviewFinalizeExplanation" ref="reviewFinalizeExplanationRef" class="card" style="margin-top:12px;border:1px solid var(--color-border);">
            <h3 class="card-title">复核收口结果说明</h3>
            <div class="status-bar">
              <div class="status-item"><span class="status-label">已填标签</span><span class="status-value">{{ reviewFinalizeExplanation.filledRows }}</span></div>
              <div class="status-item"><span class="status-label">人工填写</span><span class="status-value">{{ reviewFinalizeExplanation.manualRows }}</span></div>
              <div class="status-item"><span class="status-label">当前 pending</span><span class="status-value">{{ reviewFinalizeExplanation.pendingSegments }}</span></div>
              <div class="status-item"><span class="status-label">Transition 主段</span><span class="status-value">{{ reviewFinalizeExplanation.transitionPrimaryCount }}</span></div>
            </div>
            <div class="event-list" style="margin-top:12px;">
              <div class="event-row"><span>当前在做什么</span><span style="color:var(--color-text-muted)">{{ reviewFinalizeExplanation.currentAction }}</span></div>
              <div class="event-row"><span>下一步</span><span style="color:var(--color-text-muted)">{{ reviewFinalizeExplanation.nextAction }}</span></div>
              <div class="event-row" v-for="item in reviewFinalizeExplanation.pendingItems" :key="item.segment_id">
                <span>{{ item.segment_id }}</span>
                <span style="color:var(--color-text-muted)">{{ item.support_status_v3 }} | memory={{ item.memory_role_v2 ?? 'none' }}</span>
              </div>
            </div>
            <div class="status-label" style="margin-top:12px;">关键输出文件</div>
            <div class="event-list">
              <div class="event-row" v-for="item in reviewFinalizeExplanation.outputItems" :key="item.label">
                <span>{{ item.label }}</span>
                <span style="color:var(--color-text-muted)">{{ item.path }}</span>
              </div>
            </div>
          </div>
          <div v-if="reviewFinalizeResult" class="json-box">{{ JSON.stringify(reviewFinalizeResult, null, 2) }}</div>
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
              <span :class="['badge', triStateBadgeClass(e.detection)]">{{ triStateLabel(e.detection) }}</span>
              <span style="color:var(--color-text-muted)">{{ e.detection?.model_name }} | {{ e.method }} | {{ e.detection?.status_label || e.detection?.status }}</span>
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
              <span :class="['badge', triStateBadgeClass(row)]">{{ triStateLabel(row) }}</span>
              <span style="color:var(--color-text-muted)">{{ row.model_name }} | {{ row.method }} | {{ row.status_label || row.diagnosis_status }}</span>
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

    <div v-if="showAnomalyDetailModal" class="modal-mask" @click.self="closeAnomalyDetail">
      <div class="modal-card anomaly-detail-card">
        <div class="modal-header">
          <h3>{{ anomalyDetailTitle }}</h3>
          <button class="nav-tab cursor-pointer" @click="closeAnomalyDetail">关闭</button>
        </div>
        <div class="status-bar">
          <div class="status-item">
            <span class="status-label">判定级别</span>
            <span class="status-value">
              <span :class="['badge', triStateBadgeClass(anomalyDetailRow)]">{{ triStateLabel(anomalyDetailRow) }}</span>
            </span>
          </div>
          <div class="status-item">
            <span class="status-label">执行状态</span>
            <span class="status-value">{{ anomalyDetailRow?.status_label || anomalyDetailRow?.status || '--' }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">异常分数</span>
            <span class="status-value">{{ formatFixed(anomalyDetailRow?.anomaly_score, 4) }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">阈值</span>
            <span class="status-value">{{ formatFixed(anomalyDetailRow?.threshold, 4) }}</span>
          </div>
        </div>
        <div class="status-label" style="margin-top:12px;color:var(--color-text-muted);">
          {{ anomalyDetailGuidance }}
        </div>
        <div class="event-list" style="max-height:420px;margin-top:10px;">
          <div class="event-row" v-for="item in anomalyDetailItems" :key="item.label">
            <span>{{ item.label }}</span>
            <span class="detail-value">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import TrendChart from './components/TrendChart.vue'
import {
  compareDeviceModels,
  createDiagSSE,
  createHomeSSE,
  fetchAdminRecent,
  buildFaultRecentExportUrl,
  fetchFaultRecent,
  fetchModelResponseRecent,
  fetchModelResponseSummary,
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
  fetchNewDataReviewConfig,
  finalizeNewDataReviewWorkflow,
  rollbackModelVersion,
  selectModel,
  selectDeviceModel,
  startDiagnosisReplay,
  triggerProcess,
  uploadLocalXlsx,
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

const queryDev = ref('')
const queryHours = ref(48)
const querying = ref(false)
const deviceData = ref(null)
const deviceQueryMessage = ref('')
const comparingModels = ref(false)
const deviceModelCompareMessage = ref('')
const deviceModelCompareResult = ref(null)
const compareHours = ref(48)
const compareRangeMode = ref('hours')
const compareMaxScanPoints = ref(120)
const compareSelectedModels = ref([])
const comparePreviewModelName = ref('')

const availableModels = ref([])
const modelServiceAvailable = ref(true)
const modelServiceMessage = ref('')
const homeSelectedModel = ref('auto')
const homeEffectiveModel = ref('auto')
const switchingHomeModel = ref(false)
const homeModelMessage = ref('')
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
const analysisSource = ref('all')
const analysisHours = ref(72)
const analysisDevKeyword = ref('')
const analysisLoading = ref(false)
const analysisMessage = ref('')
const analysisSummaryRows = ref([])
const analysisRecentAnomalies = ref([])
const showAnomalyDetailModal = ref(false)
const anomalyDetailRow = ref(null)
const anomalyDetailSource = ref('')
const rollbackModelCatalog = computed(() => modelCatalog.value.filter((x) => x.rollback_supported && x.enabled))
const rollbackVersions = computed(() => {
  const model = rollbackModelCatalog.value.find((x) => x.model_name === rollbackModelName.value)
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
const selectedDeviceModelConfig = computed(() => modelCatalog.value.find((x) => x.model_name === deviceSelectedModel.value) || null)
const compareModelOptions = computed(() => modelCatalog.value.filter((x) => x.enabled && x.model_name !== 'none'))
const comparePreviewOptions = computed(() => (deviceModelCompareResult.value?.results || []).filter((x) => x.available))
const comparePreviewRow = computed(() => {
  const modelName = String(comparePreviewModelName.value || '').trim()
  if (!modelName) return null
  return (deviceModelCompareResult.value?.results || []).find((x) => x.model_name === modelName) || null
})
const deviceChartMarks = computed(() => {
  if (comparePreviewRow.value?.marks?.length) return comparePreviewRow.value.marks
  return Array.isArray(deviceData.value?.marks) ? deviceData.value.marks : []
})
const deviceChartMarkSourceText = computed(() => {
  if (comparePreviewRow.value?.model_name) {
    return `当前图表标记来源：对比模型 ${comparePreviewRow.value.model_name}`
  }
  return '当前图表标记来源：实时检测结果'
})
const selectedDeviceModelEnabled = computed(() => {
  if (deviceSelectedModel.value === 'none') return true
  return !!selectedDeviceModelConfig.value?.enabled
})
const uploadFile = ref(null)
const uploadModelName = ref('seal_v4')
const uploadDevHint = ref('')
const uploadProcessMode = ref('full')
const uploadingXlsx = ref(false)
const uploadResult = ref(null)
const uploadMessage = ref('')
const reviewFinalizeReadmeXlsx = ref('/Users/xpker/Downloads/data_readme.xlsx')
const reviewFinalizeManifestCsv = ref('reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv')
const reviewFinalizeSupportCsv = ref('reports/new_data_segment_static_support_v3_run1/segment_support_output_v3.csv')
const reviewFinalizeQueueCsv = ref('reports/new_data_segment_static_support_v3_run1/segment_review_queue_v3.csv')
const reviewFinalizeLabelsCsv = ref('reports/new_data_review_workflow_v1_run1/segment_review_labels_working_v2.csv')
const reviewFinalizeAutoSeedCsv = ref('reports/new_data_segment_auto_seed_labels_v2_run1/segment_review_labels_auto_seed_v2.csv')
const reviewFinalizeOutputDir = ref('reports/new_data_review_finalize_v1_run1')
const reviewFinalizeSubmitting = ref(false)
const reviewFinalizeResult = ref(null)
const reviewFinalizeMessage = ref('')
const reviewFinalizeConfig = ref(null)
const reviewFinalizeExplanationRef = ref(null)
const deviceMarkPreview = computed(() => {
  const marks = Array.isArray(deviceChartMarks.value) ? [...deviceChartMarks.value] : []
  return marks
    .sort((a, b) => Number(b.display_mark_ts || 0) - Number(a.display_mark_ts || 0))
    .slice(0, 8)
})
const deviceTransitionEvent = computed(() => deviceData.value?.latest_detection?.transition_event || null)
const deviceScanSummaryText = computed(() => {
  const summary = deviceData.value?.scan_summary
  if (!summary?.window_count) return ''
  const counts = summary.abnormal_label_counts || {}
  const labelText = Object.entries(counts)
    .map(([label, count]) => `${label}: ${count}`)
    .join('，')
  const base = `SALAD 滑窗：${summary.window_hours}h 窗口 / ${summary.step_hours}h 步进，异常窗口 ${summary.abnormal_window_count}/${summary.window_count}`
  return labelText ? `${base}（${labelText}）` : base
})
const reviewFinalizeFileStatus = computed(() => {
  const fileStatus = reviewFinalizeConfig.value?.file_status || {}
  const labels = {
    readme_xlsx: '说明 Excel',
    segment_manifest_csv: '段清单 CSV',
    segment_support_csv: '支撑结果 CSV',
    review_queue_csv: '复核队列 CSV',
    working_labels_csv: '工作标签 CSV',
    auto_seed_csv: '自动种子 CSV',
    output_dir: '输出目录',
  }
  return Object.entries(fileStatus).map(([key, meta]) => ({
    key,
    label: labels[key] || key,
    path: meta?.path || '--',
    exists: !!meta?.exists,
    isDir: !!meta?.is_dir,
  }))
})
const reviewFinalizeExplanation = computed(() => {
  const data = reviewFinalizeResult.value?.data
  const summary = data?.summary || {}
  const feedback = summary?.feedback_summary || {}
  const tuning = summary?.tuning_summary || {}
  const outputs = data?.outputs || {}
  if (!reviewFinalizeResult.value || reviewFinalizeResult.value.code !== 0) return null
  return {
    filledRows: summary?.filled_rows ?? '--',
    manualRows: summary?.manual_rows ?? '--',
    pendingSegments: feedback?.pending_segments ?? '--',
    transitionPrimaryCount: tuning?.transition_primary_segment_count ?? '--',
    currentAction: '把人工复核结果重新回灌到段级参考池，并刷新 guarded/pending 排序。',
    nextAction: (feedback?.pending_segments || 0) > 0
      ? '继续优先复核 181049 和 transition_secondary_control，暂不重启 whole-run 模型。'
      : '当前 pending 已清空，可以进入下一轮段级基准维护或阈值微调。',
    pendingItems: feedback?.top_pending_segments || [],
    outputItems: [
      { label: '收口报告', path: outputs?.finalize_report_md || '--' },
      { label: 'Pending 重排', path: outputs?.pending_csv || '--' },
      { label: '调优建议', path: outputs?.tuning_report_md || '--' },
      { label: '标签快照', path: outputs?.snapshot_csv || '--' },
    ],
  }
})

const STATUS_GUIDANCE_MAP = {
  transition_boost_alert: '检测到湿度转移增强，建议优先排查密封胶条、线束入口与排水通道。',
  static_dynamic_supported_alert: '当前高湿响应支持异常，建议结合温湿趋势复核是否持续进湿。',
  static_dynamic_support_alert: '当前高湿响应支持异常，建议结合温湿趋势复核是否持续进湿。',
  static_hard_case_watch: '当前为难例观察状态，建议继续积累更多时间窗再复核结论。',
  static_abstain_low_signal: '当前信号较弱，模型保守判定，建议延长采样窗口后再判断。',
  heat_related_background: '当前更像热相关背景变化，建议结合外部工况确认。',
  low_info_background: '当前信息量较低，建议补充更多采样点。',
  insufficient_data: '当前数据不足，建议确认设备是否持续上报。',
  insufficient_history_local: '历史窗口不足，建议延长时间范围后重试。',
  ongoing: '识别为进行中的异常事件，建议尽快现场排查。',
  no_detection: '未检出异常，但建议结合现场工况持续观察。',
  salad_low_info: 'SALAD 判定为低信息工况，建议补充更多连续数据。',
  salad_sealed: 'SALAD 判定密封正常，当前风险较低。',
  salad_unsealed: 'SALAD 判定密封异常，建议优先排查箱体密封路径。',
  salad_moisture_ingress: 'SALAD 判定持续进湿，建议检查进湿源与密封完整性。',
  salad_moisture_accumulation: 'SALAD 判定内部积湿，建议检查冷凝与排湿条件。',
  salad_unknown: 'SALAD 当前未给出明确结果，建议继续观察或换窗复核。',
  salad_error: 'SALAD 运行异常，建议检查模型服务与输入数据质量。',
}

const anomalyDetailTitle = computed(() => {
  const row = anomalyDetailRow.value || {}
  return `异常详情：${row.dev_num || '--'}`
})

const anomalyDetailGuidance = computed(() => {
  const row = anomalyDetailRow.value || {}
  const status = String(row.status || row.diagnosis_status || '').trim()
  if (status && STATUS_GUIDANCE_MAP[status]) return STATUS_GUIDANCE_MAP[status]
  const risk = String(row.risk_level || '').trim()
  if (risk === 'high') return '当前为高风险异常，建议先做现场复检，再结合模型回放确认趋势。'
  if (risk === 'watch') return '当前为观察状态，建议继续跟踪后续数据再下结论。'
  return '当前结果多为低风险或背景状态，建议结合时间窗持续观察。'
})

const anomalyDetailItems = computed(() => {
  const row = anomalyDetailRow.value || {}
  const source = row.source || (anomalyDetailSource.value === 'admin_recent' ? 'online' : '--')
  return [
    { label: '设备号', value: row.dev_num || '--' },
    { label: '检测时间', value: formatTime(row.device_timestamp) },
    { label: '来源', value: source },
    { label: '请求模型', value: row.requested_model_name || row.model_name || '--' },
    { label: '生效模型', value: row.effective_model_name || row.model_name || '--' },
    { label: '模型版本', value: row.model_version || '--' },
    { label: '执行状态代码', value: row.status || row.diagnosis_status || '--' },
    { label: '执行状态展示', value: row.status_label || row.status_short || row.status || '--' },
    { label: '风险级别', value: row.risk_level || '--' },
    { label: '分数', value: formatFixed(row.anomaly_score, 4) },
    { label: '阈值', value: formatFixed(row.threshold, 4) },
    { label: '耗时', value: row.infer_latency_ms != null ? `${row.infer_latency_ms}ms` : '--' },
    { label: '请求ID', value: row.request_id || row.run_id || '--' },
    { label: '运行ID', value: row.run_id || row.request_id || '--' },
    { label: '错误详情', value: row.error_detail || '--' },
  ]
})

async function loadReviewFinalizeDefaults() {
  try {
    const r = await fetchNewDataReviewConfig()
    reviewFinalizeConfig.value = r.code === 0 ? r.data : null
    const defaults = r.data?.defaults || {}
    if (r.code === 0) {
      reviewFinalizeReadmeXlsx.value = defaults.readme_xlsx || reviewFinalizeReadmeXlsx.value
      reviewFinalizeManifestCsv.value = defaults.segment_manifest_csv || reviewFinalizeManifestCsv.value
      reviewFinalizeSupportCsv.value = defaults.segment_support_csv || reviewFinalizeSupportCsv.value
      reviewFinalizeQueueCsv.value = defaults.review_queue_csv || reviewFinalizeQueueCsv.value
      reviewFinalizeLabelsCsv.value = defaults.working_labels_csv || reviewFinalizeLabelsCsv.value
      reviewFinalizeAutoSeedCsv.value = defaults.auto_seed_csv || reviewFinalizeAutoSeedCsv.value
      reviewFinalizeOutputDir.value = defaults.output_dir || reviewFinalizeOutputDir.value
    }
  } catch {
    reviewFinalizeConfig.value = null
  }
}

function formatTime(ts) {
  if (!ts) return '--'
  const v = ts > 1e12 ? ts : ts * 1000
  return new Date(v).toLocaleString('zh-CN')
}

function formatFixed(value, digits = 4) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '--'
  return num.toFixed(digits)
}

function badgeClassByTone(item) {
  const tone = String(item?.tone || '').trim()
  const risk = String(item?.risk_level || '').trim()
  if (tone === 'danger' || risk === 'high') return 'badge-anomaly'
  if (tone === 'warning' || risk === 'watch') return 'badge-warning'
  return 'badge-muted'
}

function triStateTone(item) {
  const tone = String(item?.tone || '').trim()
  const risk = String(item?.risk_level || '').trim()
  const status = String(item?.status || item?.diagnosis_status || '').trim()
  if (tone === 'danger' || risk === 'high' || item?.is_anomaly) return 'danger'
  if (tone === 'warning' || risk === 'watch' || status.includes('watch')) return 'warning'
  return 'ok'
}

function triStateBadgeClass(item) {
  const tone = triStateTone(item)
  if (tone === 'danger') return 'badge-anomaly'
  if (tone === 'warning') return 'badge-warning'
  return 'badge-ok'
}

function triStateLabel(item) {
  const tone = triStateTone(item)
  if (tone === 'danger') return '异常'
  if (tone === 'warning') return '观察'
  return '正常'
}

function openAnomalyDetail(row, source = 'admin_recent') {
  anomalyDetailRow.value = row ? { ...row } : null
  anomalyDetailSource.value = source
  showAnomalyDetailModal.value = !!row
}

function closeAnomalyDetail() {
  showAnomalyDetailModal.value = false
  anomalyDetailRow.value = null
  anomalyDetailSource.value = ''
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
    status_label: raw.status_label || '',
    status_short: raw.status_short || '',
    anomaly_score: raw.anomaly_score,
    risk_level: raw.risk_level || '',
    tone: raw.tone || '',
  }
}

function isModelEnabled(modelName) {
  const model = modelCatalog.value.find((x) => x.model_name === modelName)
  return !!model?.enabled
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
  deviceModelCompareResult.value = null
  deviceModelCompareMessage.value = ''
  comparePreviewModelName.value = ''
  try {
    const dev = queryDev.value.trim()
    if (!dev) {
      deviceData.value = null
      deviceQueryMessage.value = '请输入设备编号'
      return
    }

    // 查询前按当前选择处理模型：none=仅查询；其他=先尝试切换模型再查询
    if (deviceSelectedModel.value !== 'none') {
      const selectedCfg = modelCatalog.value.find((x) => x.model_name === deviceSelectedModel.value)
      if (!selectedCfg?.enabled) {
        deviceData.value = null
        deviceQueryMessage.value = `当前模型 ${deviceSelectedModel.value} 不可用，请切换为 seal_v4、auto 或 none`
        return
      }
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
    compareHours.value = hours

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
      const resolvedDev = String(curveRes.data?.dev_num || dev).trim()
      if (resolvedDev && resolvedDev !== dev) {
        queryDev.value = resolvedDev
        deviceQueryMessage.value = `已自动识别设备号：${resolvedDev}`
      }
      const anomalyRes = await fetchDeviceAnomalies(resolvedDev, queryHours.value)
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
      modelServiceMessage.value = modelEnabled ? '' : '当前未提供 xgboost/gru 模型，仍可使用 seal_v4 / salad_gru / auto 进行本地检测'
      const models = r.data?.models || []
      availableModels.value = models.filter((m) => m.enabled)
      modelCatalog.value = models
      if (!compareSelectedModels.value.length) {
        compareSelectedModels.value = models
          .filter((m) => m.enabled && m.model_name !== 'none')
          .slice(0, 2)
          .map((m) => m.model_name)
      }
      homeSelectedModel.value = r.data?.default_model || homeSelectedModel.value || 'auto'
      homeEffectiveModel.value = r.data?.effective_model_name || homeSelectedModel.value

      const firstRollbackModel = models.find((m) => m.rollback_supported && m.enabled)
      if (firstRollbackModel) {
        rollbackModelName.value = firstRollbackModel.model_name
        rollbackTargetVersion.value = firstRollbackModel.active_version || firstRollbackModel.latest_version || ''
      } else {
        rollbackModelName.value = ''
        rollbackTargetVersion.value = ''
      }
      return
    }

    modelServiceAvailable.value = false
    modelServiceMessage.value = r.message || '模型目录暂不可用'
    availableModels.value = []
    modelCatalog.value = []
    homeSelectedModel.value = 'auto'
    homeEffectiveModel.value = 'auto'
    deviceSelectedModel.value = 'none'
  } catch (err) {
    modelServiceAvailable.value = false
    modelServiceMessage.value = err?.message || '模型服务暂不可用，当前仅支持 none 查询模式'
    availableModels.value = []
    modelCatalog.value = []
    homeSelectedModel.value = 'auto'
    homeEffectiveModel.value = 'auto'
    deviceSelectedModel.value = 'none'
  }
}

async function saveHomeModel() {
  if (!isModelEnabled(homeSelectedModel.value)) {
    homeModelMessage.value = `当前模型 ${homeSelectedModel.value} 不可用`
    setTimeout(() => {
      homeModelMessage.value = ''
    }, 2500)
    return
  }
  switchingHomeModel.value = true
  homeModelMessage.value = ''
  try {
    const r = await selectModel(homeSelectedModel.value)
    if (r.code === 0) {
      homeSelectedModel.value = r.data?.default_model || homeSelectedModel.value
      homeEffectiveModel.value = r.data?.effective_model_name || homeSelectedModel.value
      homeModelMessage.value = `首页默认模型已切换为 ${homeSelectedModel.value}`
      setTimeout(() => {
        homeModelMessage.value = ''
      }, 2500)
    } else {
      homeModelMessage.value = r.message || '首页模型切换失败'
    }
  } catch (err) {
    homeModelMessage.value = err?.message || '首页模型切换异常'
  } finally {
    switchingHomeModel.value = false
  }
}

async function loadDeviceModel(devNum, keepNoneSelection = false) {
  if (!devNum) return
  const r = await fetchDeviceModel(devNum)
  if (r.code === 0 && r.data) {
    if (!(keepNoneSelection && deviceSelectedModel.value === 'none')) {
      deviceSelectedModel.value = r.data.model_name
    }
    const effective = r.data.effective_model_name
    deviceModelSource.value = effective && effective !== r.data.model_name ? `${r.data.source} -> ${effective}` : r.data.source
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
  if (!selectedDeviceModelEnabled.value) {
    deviceModelSaveMessage.value = `当前模型 ${deviceSelectedModel.value} 不可用`
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

function toggleCompareModel(modelName, checked) {
  const current = new Set(compareSelectedModels.value)
  if (checked) current.add(modelName)
  else current.delete(modelName)
  compareSelectedModels.value = Array.from(current)
}

function clearComparePreview() {
  comparePreviewModelName.value = ''
}

async function runDeviceModelCompare() {
  const dev = queryDev.value.trim()
  if (!dev) {
    deviceModelCompareMessage.value = '请先输入设备编号并查询'
    return
  }
  if (!compareSelectedModels.value.length) {
    deviceModelCompareMessage.value = '请至少选择一个模型'
    return
  }

  const fallbackEnd = Date.now()
  let rangeStart = fallbackEnd - Math.max(1, Number(compareHours.value) || 48) * 3600 * 1000
  let rangeEnd = fallbackEnd
  let rangeModeText = `最近 ${Math.max(1, Number(compareHours.value) || 48)} 小时`
  if (
    compareRangeMode.value === 'current'
    && deviceData.value?.range?.start_ts
    && deviceData.value?.range?.end_ts
  ) {
    rangeStart = Number(deviceData.value.range.start_ts)
    rangeEnd = Number(deviceData.value.range.end_ts)
    rangeModeText = '当前查询区间'
  } else if (compareRangeMode.value === 'current') {
    deviceModelCompareMessage.value = '当前没有可用查询区间，已自动按“对比小时数”窗口执行'
  }

  comparingModels.value = true
  if (!deviceModelCompareMessage.value.includes('已自动按“对比小时数”窗口执行')) {
    deviceModelCompareMessage.value = ''
  }
  deviceModelCompareResult.value = null
  try {
    const res = await compareDeviceModels({
      dev_num: dev,
      start_ts: rangeStart,
      end_ts: rangeEnd,
      model_names: compareSelectedModels.value,
      max_scan_points: Math.max(20, Math.min(300, Number(compareMaxScanPoints.value) || 120)),
    })
    if (res.code === 0) {
      deviceModelCompareResult.value = res.data
      const resolvedDev = String(res.data?.dev_num || dev).trim()
      if (resolvedDev && resolvedDev !== dev) {
        queryDev.value = resolvedDev
      }
      const firstAvailable = (res.data?.results || []).find((x) => x.available)
      comparePreviewModelName.value = firstAvailable?.model_name || ''
      const count = res.data?.results?.length || 0
      const scanPoints = res.data?.range?.scan_points ?? '--'
      const seriesPoints = res.data?.range?.series_points ?? '--'
      deviceModelCompareMessage.value = `对比完成，共 ${count} 个模型；区间=${rangeModeText}；扫描点=${scanPoints}（原始点=${seriesPoints}）`
    } else {
      deviceModelCompareMessage.value = res.message || '模型对比失败'
    }
  } catch (err) {
    deviceModelCompareMessage.value = err?.message || '模型对比异常'
  } finally {
    comparingModels.value = false
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

async function loadModelResponseInsights() {
  analysisLoading.value = true
  analysisMessage.value = ''
  try {
    const hours = Math.min(Math.max(Number(analysisHours.value) || 72, 1), 8760)
    analysisHours.value = hours
    const dev = analysisDevKeyword.value.trim()
    const source = analysisSource.value || 'all'

    const [summaryRes, recentRes] = await Promise.all([
      fetchModelResponseSummary(source, hours, dev),
      fetchModelResponseRecent(200, source, hours, dev, '', true),
    ])

    if (summaryRes.code === 0) {
      const rows = summaryRes.data?.items || []
      analysisSummaryRows.value = rows.map((x) => ({
        ...x,
        anomaly_rate: Number(x.anomaly_rate || 0) * 100,
      }))
    } else {
      analysisSummaryRows.value = []
    }

    if (recentRes.code === 0) {
      analysisRecentAnomalies.value = recentRes.data?.items || []
    } else {
      analysisRecentAnomalies.value = []
    }
    if (!analysisSummaryRows.value.length && !analysisRecentAnomalies.value.length) {
      analysisMessage.value = '当前筛选条件下暂无模型响应数据。请先在“设备查询 > 模型对比回放”执行一次，或等待新的实时检测写入后再刷新。'
    } else if (!analysisRecentAnomalies.value.length) {
      analysisMessage.value = '已加载模型响应汇总；当前时间窗内暂无异常响应明细。'
    }
  } catch (err) {
    analysisSummaryRows.value = []
    analysisRecentAnomalies.value = []
    analysisMessage.value = `刷新失败：${err?.message || '请检查后端服务是否已更新并重启'}`
  } finally {
    analysisLoading.value = false
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

function onUploadFileChange(evt) {
  const files = evt?.target?.files
  uploadFile.value = files && files.length ? files[0] : null
}

async function submitUploadXlsx() {
  if (!uploadFile.value) {
    uploadMessage.value = '请先选择 Excel 文件'
    return
  }
  uploadingXlsx.value = true
  uploadResult.value = null
  uploadMessage.value = ''
  try {
    const r = await uploadLocalXlsx(
      uploadFile.value,
      uploadModelName.value,
      uploadDevHint.value.trim(),
      uploadProcessMode.value,
    )
    uploadResult.value = r
    if (r.code === 0 && r.data?.dev_num) {
      queryDev.value = r.data.dev_num
      deviceSelectedModel.value = r.data.model_name || 'seal_v4'
      deviceData.value = r.data.detail || null
      deviceQueryMessage.value = `当前展示为上传文件内存分析结果：${r.data.file_name}。如手动重新查询，将切回数据库设备查询。`
      page.value = 'device'
      if (r.data?.latest_detection?.error_detail) {
        uploadMessage.value = `上传完成，但 SALAD 返回异常：${r.data.latest_detection.error_detail}`
      } else {
        uploadMessage.value = `上传成功，已完成内存批量检测：${r.data.dev_num}`
      }
    } else {
      uploadMessage.value = r.message || '上传失败'
    }
  } catch (err) {
    uploadMessage.value = err?.message || '上传异常'
  } finally {
    uploadingXlsx.value = false
  }
}

async function submitReviewFinalize() {
  reviewFinalizeSubmitting.value = true
  reviewFinalizeResult.value = null
  reviewFinalizeMessage.value = ''
  try {
    const payload = {
      readme_xlsx: reviewFinalizeReadmeXlsx.value.trim(),
      segment_manifest_csv: reviewFinalizeManifestCsv.value.trim(),
      segment_support_csv: reviewFinalizeSupportCsv.value.trim(),
      review_queue_csv: reviewFinalizeQueueCsv.value.trim(),
      working_labels_csv: reviewFinalizeLabelsCsv.value.trim(),
      auto_seed_csv: reviewFinalizeAutoSeedCsv.value.trim(),
      output_dir: reviewFinalizeOutputDir.value.trim(),
    }
    const r = await finalizeNewDataReviewWorkflow(payload)
    reviewFinalizeResult.value = r
    if (r.code === 0) {
      const pending = r.data?.summary?.feedback_summary?.pending_segments
      reviewFinalizeMessage.value = `复核收口完成，当前剩余 pending：${pending ?? '--'}`
      await nextTick()
      reviewFinalizeExplanationRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      reviewFinalizeMessage.value = r.message || '复核收口失败'
    }
  } catch (err) {
    reviewFinalizeMessage.value = err?.message || '复核收口异常'
  } finally {
    reviewFinalizeSubmitting.value = false
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
  if (!rollbackModelCatalog.value.length) {
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

watch([deviceSelectedModel, modelCatalog], ([selected]) => {
  if (selected === 'none') {
    deviceModelSource.value = 'none'
  }
})

watch(compareModelOptions, (options) => {
  const validNames = new Set(options.map((x) => x.model_name))
  const filtered = compareSelectedModels.value.filter((name) => validNames.has(name))
  if (filtered.length) {
    compareSelectedModels.value = filtered
    return
  }
  compareSelectedModels.value = options.slice(0, 2).map((x) => x.model_name)
})

watch(comparePreviewOptions, (options) => {
  if (!comparePreviewModelName.value) return
  const valid = options.some((x) => x.model_name === comparePreviewModelName.value)
  if (!valid) comparePreviewModelName.value = ''
})

watch([adminStatusFilter, adminPageSize, adminSortBy, adminSortOrder], async () => {
  adminPage.value = 1
  syncAdminStateToUrl()
  await loadAdminRecent()
})

watch([analysisSource, analysisHours], async () => {
  if (page.value !== 'admin') return
  await loadModelResponseInsights()
})

watch(page, async (v) => {
  if (v !== 'admin') {
    closeAnomalyDetail()
    return
  }
  if (!analysisSummaryRows.value.length && !analysisRecentAnomalies.value.length) {
    await loadModelResponseInsights()
  }
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
    loadReviewFinalizeDefaults(),
    loadHomeCurrent(),
    loadHomeTicker(),
    loadDeviceStatsAndIds(),
    loadAdminRecent(),
    loadModelResponseInsights(),
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
