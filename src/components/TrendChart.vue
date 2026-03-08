<template>
  <div ref="chartRef" class="chart-container"></div>
</template>
 
<script setup>
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue'
import * as echarts from 'echarts'
 
const props = defineProps({
  series: { type: Array, default: () => [] },
  marks: { type: Array, default: () => [] },
  showZoom: { type: Boolean, default: false },
})
 
const chartRef = ref(null)
const chart = shallowRef(null)
 
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
 
function buildOption() {
  const times = props.series.map(p => formatTs(p.ts))
  const inTemp = props.series.map(p => p.in_temp)
  const outTemp = props.series.map(p => p.out_temp)
  const inHum = props.series.map(p => p.in_hum)
  const outHum = props.series.map(p => p.out_hum)
 
  const markPoints = props.marks
    .filter(m => m.display_mark_ts)
    .map(m => {
      const label = formatTs(m.display_mark_ts)
      const idx = times.indexOf(label)
      return idx >= 0
        ? { coord: [idx, inTemp[idx]], value: '!', symbol: 'pin', symbolSize: 36, itemStyle: { color: '#EF4444' } }
        : null
    })
    .filter(Boolean)
 
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
      backgroundColor: '#1E293B',
      borderColor: '#334155',
      textStyle: { color: '#F8FAFC', fontSize: 12, fontFamily: 'Fira Sans' },
      extraCssText: 'box-shadow: 0 4px 12px rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.2);',
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
      { ...seriesBase, name: '内部温度', data: inTemp, yAxisIndex: 0, color: '#22C55E', markPoint: { data: markPoints } },
      { ...seriesBase, name: '外部温度', data: outTemp, yAxisIndex: 0, color: '#3B82F6' },
      { ...seriesBase, name: '内部湿度', data: inHum, yAxisIndex: 1, color: '#F59E0B' },
      { ...seriesBase, name: '外部湿度', data: outHum, yAxisIndex: 1, color: '#A855F7' },
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
