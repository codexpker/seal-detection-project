<template>
  <div ref="chartRef" class="chart-container"></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  series: { type: Array, default: () => [] },
  marks: { type: Array, default: () => [] },
  showZoom: { type: Boolean, default: false },
})

const chartRef = ref(null)
const chart = shallowRef(null)

const STATUS_META = {
  transition_boost_alert: {
    label: '转移增强告警',
    short: '转移告警',
    color: '#ef4444',
    areaColor: 'rgba(239, 68, 68, 0.10)',
    riskLevel: 'high',
  },
  static_dynamic_supported_alert: {
    label: '高湿响应支持',
    short: '高湿支持',
    color: '#f97316',
    areaColor: 'rgba(249, 115, 22, 0.10)',
    riskLevel: 'high',
  },
  static_dynamic_support_alert: {
    label: '高湿响应支持',
    short: '高湿支持',
    color: '#f97316',
    areaColor: 'rgba(249, 115, 22, 0.10)',
    riskLevel: 'high',
  },
  static_hard_case_watch: {
    label: '难例观察',
    short: '观察',
    color: '#eab308',
    areaColor: 'rgba(234, 179, 8, 0.10)',
    riskLevel: 'watch',
  },
  static_abstain_low_signal: {
    label: '低信号',
    short: '低信号',
    color: '#94a3b8',
    areaColor: 'rgba(148, 163, 184, 0.10)',
    riskLevel: 'low',
  },
  ongoing: {
    label: '异常事件',
    short: '异常',
    color: '#ef4444',
    areaColor: 'rgba(239, 68, 68, 0.10)',
    riskLevel: 'high',
  },
  heat_related_background: {
    label: '热相关背景',
    short: '热相关',
    color: '#64748b',
    areaColor: 'rgba(100, 116, 139, 0.08)',
    riskLevel: 'low',
  },
  low_info_background: {
    label: '低信息背景',
    short: '低信息',
    color: '#64748b',
    areaColor: 'rgba(100, 116, 139, 0.08)',
    riskLevel: 'low',
  },
  no_detection: {
    label: '无检测',
    short: '无检测',
    color: '#64748b',
    areaColor: 'rgba(100, 116, 139, 0.08)',
    riskLevel: 'low',
  },
}

function formatTs(ts) {
  const v = ts > 1e12 ? ts : ts * 1000
  const d = new Date(v)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const MM = String(d.getMonth() + 1).padStart(2, '0')
  const DD = String(d.getDate()).padStart(2, '0')
  return `${MM}-${DD} ${hh}:${mm}:${ss}`
}

function normalizeTs(ts) {
  const value = Number(ts || 0)
  if (!Number.isFinite(value) || value <= 0) return 0
  return value > 1e12 ? value : value * 1000
}

function formatNumber(value, digits = 3) {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(digits) : '--'
}

function getStatusMeta(mark = {}) {
  const key = String(mark.status || '').trim()
  const meta = STATUS_META[key] || {
    label: key || '异常标记',
    short: key ? key.replace(/_/g, ' ') : '标记',
    color: '#ef4444',
    areaColor: 'rgba(239, 68, 68, 0.10)',
    riskLevel: 'high',
  }
  return {
    key,
    ...meta,
    label: mark.status_label || meta.label,
    short: mark.status_short || meta.short,
    riskLevel: mark.risk_level || meta.riskLevel,
  }
}

function nearestIndex(values, target) {
  if (!values.length || !target) return -1
  let left = 0
  let right = values.length - 1
  while (left < right) {
    const mid = Math.floor((left + right) / 2)
    if (values[mid] < target) left = mid + 1
    else right = mid
  }
  const idx = left
  if (idx <= 0) return 0
  const prevIdx = idx - 1
  return Math.abs(values[idx] - target) < Math.abs(values[prevIdx] - target) ? idx : prevIdx
}

function buildNormalizedMarks(times, tsValues, inHum) {
  return props.marks
    .map((mark, order) => {
      const displayTs = normalizeTs(mark.display_mark_ts || mark.device_timestamp || mark.ts)
      if (!displayTs) return null
      const idx = nearestIndex(tsValues, displayTs)
      if (idx < 0 || idx >= times.length) return null
      const meta = getStatusMeta(mark)
      const startTs = normalizeTs(mark.first_detected_ts || displayTs)
      const endTs = normalizeTs(mark.last_detected_ts || displayTs)
      const startIdx = nearestIndex(tsValues, startTs)
      const endIdx = nearestIndex(tsValues, endTs)
      return {
        ...mark,
        order,
        displayTs,
        idx,
        xLabel: times[idx],
        yHum: Number(inHum[idx]),
        startIdx,
        endIdx,
        color: meta.color,
        areaColor: meta.areaColor,
        label: meta.label,
        short: meta.short,
        riskLevel: meta.riskLevel,
      }
    })
    .filter(Boolean)
}

function mergeBandRanges(normalizedMarks, times, denseMarks) {
  if (!normalizedMarks.length) return []
  const ranges = normalizedMarks
    .map((mark) => {
      const startIdx = Math.max(0, Math.min(mark.startIdx, mark.endIdx))
      const endIdx = Math.max(mark.startIdx, mark.endIdx)
      return {
        startIdx,
        endIdx,
        marks: [mark],
      }
    })
    .sort((a, b) => a.startIdx - b.startIdx || a.endIdx - b.endIdx)

  const merged = []
  for (const range of ranges) {
    const prev = merged[merged.length - 1]
    if (!prev || range.startIdx > prev.endIdx + 1) {
      merged.push({ ...range })
      continue
    }
    prev.endIdx = Math.max(prev.endIdx, range.endIdx)
    prev.marks.push(...range.marks)
  }

  return merged.map((range, index) => {
    const dominant = range.marks.reduce((best, current) => {
      const bestScore = best?.riskLevel === 'high' ? 2 : best?.riskLevel === 'watch' ? 1 : 0
      const curScore = current?.riskLevel === 'high' ? 2 : current?.riskLevel === 'watch' ? 1 : 0
      return curScore >= bestScore ? current : best
    }, range.marks[0])
    const areaColor = dominant?.riskLevel === 'high'
      ? (denseMarks ? 'rgba(239, 68, 68, 0.14)' : 'rgba(239, 68, 68, 0.10)')
      : (dominant?.areaColor || 'rgba(239, 68, 68, 0.10)')
    return {
      bandId: `band_${index + 1}`,
      startIdx: range.startIdx,
      endIdx: range.endIdx,
      xStart: times[range.startIdx],
      xEnd: times[range.endIdx === range.startIdx ? Math.min(times.length - 1, range.endIdx + 1) : range.endIdx],
      color: dominant?.color || '#ef4444',
      areaColor,
      label: dominant?.label || '异常窗口',
      short: dominant?.short || '异常',
      riskLevel: dominant?.riskLevel || 'high',
      anomalyScore: dominant?.anomaly_score,
      primaryEvidence: dominant?.primary_evidence,
      firstDetectedTs: Math.min(...range.marks.map((mark) => normalizeTs(mark.first_detected_ts || mark.displayTs))),
      lastDetectedTs: Math.max(...range.marks.map((mark) => normalizeTs(mark.last_detected_ts || mark.displayTs))),
    }
  })
}

function buildBandEndpointMarkers(mergedBands, times, inHum, denseMarks) {
  return mergedBands.flatMap((band) => {
    const startY = Number(inHum[band.startIdx])
    const endY = Number(inHum[band.endIdx])
    const startLabelText = `${denseMarks ? band.short : band.label}开始`
    const endLabelText = `${denseMarks ? band.short : band.label}结束`
    return [
      {
        bandId: band.bandId,
        idx: band.startIdx,
        xLabel: times[band.startIdx],
        yHum: Number.isFinite(startY) ? startY : 0,
        color: band.color,
        areaColor: band.areaColor,
        label: `${band.label}开始`,
        short: startLabelText,
        riskLevel: band.riskLevel,
        first_detected_ts: band.firstDetectedTs,
        last_detected_ts: band.lastDetectedTs,
        displayTs: band.firstDetectedTs,
        anomaly_score: band.anomalyScore,
        primary_evidence: band.primaryEvidence,
        endpointType: 'start',
        symbol: 'circle',
        symbolSize: denseMarks ? 14 : 18,
      },
      {
        bandId: band.bandId,
        idx: band.endIdx,
        xLabel: times[band.endIdx],
        yHum: Number.isFinite(endY) ? endY : 0,
        color: band.color,
        areaColor: band.areaColor,
        label: `${band.label}结束`,
        short: endLabelText,
        riskLevel: band.riskLevel,
        first_detected_ts: band.firstDetectedTs,
        last_detected_ts: band.lastDetectedTs,
        displayTs: band.lastDetectedTs,
        anomaly_score: band.anomalyScore,
        primary_evidence: band.primaryEvidence,
        endpointType: 'end',
        symbol: 'pin',
        symbolSize: denseMarks ? 24 : 30,
      },
    ]
  })
}

function buildOption() {
  if (!props.series.length) {
    return {
      backgroundColor: 'transparent',
      graphic: [
        {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无曲线数据',
            fill: '#94A3B8',
            font: '14px Fira Sans',
          },
        },
      ],
    }
  }

  const times = props.series.map((p) => formatTs(p.ts))
  const tsValues = props.series.map((p) => normalizeTs(p.ts))
  const inTemp = props.series.map((p) => p.in_temp)
  const outTemp = props.series.map((p) => p.out_temp)
  const inHum = props.series.map((p) => p.in_hum)
  const outHum = props.series.map((p) => p.out_hum)
  const normalizedMarks = buildNormalizedMarks(times, tsValues, inHum)
  const denseMarks = normalizedMarks.length > 10
  const mergedBands = mergeBandRanges(normalizedMarks, times, denseMarks)
  const endpointMarks = buildBandEndpointMarkers(mergedBands, times, inHum, denseMarks)
  const marksByIndex = endpointMarks.reduce((acc, mark) => {
    const key = mark.idx
    if (!acc.has(key)) acc.set(key, [])
    acc.get(key).push(mark)
    return acc
  }, new Map())
  const markLineData = mergedBands.flatMap((band) => ([
    {
      name: `${band.label}开始`,
      xAxis: band.xStart,
      lineStyle: {
        color: band.color,
        width: denseMarks ? 1.2 : 1.6,
        type: 'solid',
        opacity: 0.7,
      },
      label: { show: false },
    },
    {
      name: `${band.label}结束`,
      xAxis: band.xEnd,
      lineStyle: {
        color: band.color,
        width: denseMarks ? 1.2 : 1.6,
        type: 'solid',
        opacity: 0.7,
      },
      label: { show: false },
    },
  ]))

  const markAreaData = mergedBands.map((band) => ([
    {
      name: band.label,
      xAxis: band.xStart,
      itemStyle: { color: band.areaColor },
    },
    {
      xAxis: band.xEnd,
    },
  ]))

  const markScatter = endpointMarks.map((mark) => ({
    name: mark.label,
    value: [mark.xLabel, Number.isFinite(mark.yHum) ? mark.yHum : 0],
    itemStyle: {
      color: mark.color,
      borderColor: '#0f172a',
      borderWidth: 1,
      shadowBlur: 10,
      shadowColor: mark.areaColor,
    },
    symbol: mark.symbol,
    symbolSize: mark.symbolSize,
    label: {
      show: true,
      formatter: mark.short,
      position: 'top',
      color: '#F8FAFC',
      fontSize: denseMarks ? 9 : 10,
      fontFamily: 'Fira Sans',
      backgroundColor: mark.color,
      borderRadius: 6,
      padding: denseMarks ? [3, 5] : [4, 6],
      offset: [0, denseMarks ? -4 : -8],
    },
    emphasis: {
      scale: 1.15,
      label: { show: true },
    },
  }))

  const seriesBase = {
    type: 'line',
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 2 },
    sampling: 'lttb',
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: '#1E293B',
      borderColor: '#334155',
      textStyle: { color: '#F8FAFC', fontSize: 12, fontFamily: 'Fira Sans' },
      extraCssText: 'box-shadow: 0 4px 12px rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.2);',
      formatter(params) {
        const lineParams = (params || []).filter((p) => p.seriesType === 'line')
        const dataIndex = lineParams[0]?.dataIndex
        const axisLabel = lineParams[0]?.axisValueLabel || '--'
        let html = `<div style="font-weight:700;margin-bottom:6px;">${axisLabel}</div>`
        lineParams.forEach((p) => {
          html += `
            <div style="display:flex;align-items:center;gap:8px;margin:2px 0;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${p.color};"></span>
              <span style="color:#cbd5e1;min-width:64px;">${p.seriesName}</span>
              <span style="font-family:'Fira Code', monospace;">${formatNumber(p.data, 2)}</span>
            </div>
          `
        })
        const matchedMarks = marksByIndex.get(dataIndex) || []
        if (matchedMarks.length) {
          html += `<div style="margin:8px 0 6px;border-top:1px solid rgba(148,163,184,0.25);"></div>`
          matchedMarks.forEach((mark) => {
            const durationText = mark.first_detected_ts && mark.last_detected_ts && mark.first_detected_ts !== mark.last_detected_ts
              ? `${formatTs(mark.first_detected_ts)} ~ ${formatTs(mark.last_detected_ts)}`
              : formatTs(mark.displayTs)
            html += `
              <div style="margin:6px 0;padding:6px 8px;border-radius:8px;background:rgba(15,23,42,0.45);border:1px solid ${mark.color};">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                  <span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${mark.color};"></span>
                  <span style="font-weight:700;">${mark.label}</span>
                  <span style="color:#94a3b8;">${mark.riskLevel}</span>
                </div>
                <div style="color:#cbd5e1;font-size:11px;">时间：${durationText}</div>
                ${mark.anomaly_score != null ? `<div style="color:#cbd5e1;font-size:11px;">分数：${formatNumber(mark.anomaly_score, 3)}</div>` : ''}
                ${mark.primary_evidence ? `<div style="color:#cbd5e1;font-size:11px;">证据：${mark.primary_evidence}</div>` : ''}
              </div>
            `
          })
        }
        return html
      },
    },
    legend: {
      top: 0,
      textStyle: { color: '#94A3B8', fontSize: 12, fontFamily: 'Fira Sans' },
    },
    grid: {
      top: 40,
      left: 60,
      right: 20,
      bottom: props.showZoom ? 70 : 30,
    },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: '#94A3B8', fontSize: 10, rotate: 30, fontFamily: 'Fira Code' },
      axisLine: { lineStyle: { color: '#334155' } },
      axisTick: { lineStyle: { color: '#334155' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'Temp (°C)',
        nameTextStyle: { color: '#94A3B8', fontSize: 11, fontFamily: 'Fira Code' },
        axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: 'Fira Code' },
        splitLine: { lineStyle: { color: '#334155', type: 'dashed' } },
      },
      {
        type: 'value',
        name: 'Hum (%)',
        nameTextStyle: { color: '#94A3B8', fontSize: 11, fontFamily: 'Fira Code' },
        axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: 'Fira Code' },
        splitLine: { show: false },
      },
    ],
    series: [
      { ...seriesBase, name: '内部温度', data: inTemp, yAxisIndex: 0, color: '#22C55E' },
      { ...seriesBase, name: '外部温度', data: outTemp, yAxisIndex: 0, color: '#3B82F6' },
      {
        ...seriesBase,
        name: '内部湿度',
        data: inHum,
        yAxisIndex: 1,
        color: '#F59E0B',
        markLine: markLineData.length
          ? {
              symbol: 'none',
              silent: true,
              animation: false,
              data: markLineData,
            }
          : undefined,
        markArea: markAreaData.length
          ? {
              silent: true,
              animation: false,
              data: markAreaData,
            }
          : undefined,
      },
      { ...seriesBase, name: '外部湿度', data: outHum, yAxisIndex: 1, color: '#A855F7' },
      {
        name: '检测标记',
        type: 'scatter',
        yAxisIndex: 1,
        z: 30,
        data: markScatter,
        tooltip: { show: false },
      },
    ],
  }

  if (props.showZoom) {
    option.dataZoom = [
      {
        type: 'slider',
        start: 0,
        end: 100,
        bottom: 10,
        textStyle: { color: '#94A3B8', fontFamily: 'Fira Code' },
        borderColor: '#334155',
        fillerColor: 'rgba(34, 197, 94, 0.1)',
        handleStyle: { color: '#22C55E' },
      },
      { type: 'inside' },
    ]
  }

  return option
}

function render() {
  if (!chart.value) return
  chart.value.setOption(buildOption(), true)
}

let ro = null

onMounted(() => {
  chart.value = echarts.init(chartRef.value)
  render()
  ro = new ResizeObserver(() => chart.value && chart.value.resize())
  ro.observe(chartRef.value)
})

onUnmounted(() => {
  if (ro) ro.disconnect()
  if (chart.value) {
    chart.value.dispose()
    chart.value = null
  }
})

watch(() => [props.series, props.marks], render, { deep: true })
</script>
