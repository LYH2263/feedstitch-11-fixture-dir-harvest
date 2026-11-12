<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const tasks = ref([])
const detail = ref(null)
const directory = ref('fixtures')
const recursive = ref(true)
const ingest = ref(true)
const mode = ref('incremental')
const err = ref('')
const msg = ref('')
const busy = ref(false)

async function refresh() {
  tasks.value = await getJSON('/api/harvests')
  if (detail.value) {
    detail.value = await getJSON(`/api/harvests/${detail.value.id}`)
  }
}

async function runHarvest() {
  err.value = ''
  msg.value = ''
  busy.value = true
  try {
    detail.value = await postJSON('/api/harvests', {
      directory: directory.value,
      recursive: recursive.value,
      ingest: ingest.value,
      mode: mode.value,
    })
    msg.value = `采集任务 #${detail.value.id} 已完成（${detail.value.status}）`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function openTask(id) {
  err.value = ''
  msg.value = ''
  try {
    detail.value = await getJSON(`/api/harvests/${id}`)
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function ingestNow() {
  if (!detail.value) return
  err.value = ''
  msg.value = ''
  busy.value = true
  try {
    detail.value = await postJSON(`/api/harvests/${detail.value.id}/ingest`, { mode: mode.value })
    msg.value = `采集任务 #${detail.value.id} 已触发摄取`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

const reconRows = computed(() => {
  const recon = detail.value?.report?.reconciliation || {}
  return Object.entries(recon)
})

const ingestReport = computed(() => detail.value?.report?.ingest || {})

function checkTag(value) {
  if (value === null || value === undefined) return 'warn'
  return value ? 'ok' : 'danger'
}

function checkLabel(value) {
  if (value === null || value === undefined) return '未摄取'
  return value ? '对账通过' : '对账异常'
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div class="page">
    <h1>目录巡检采集</h1>
    <p class="muted">
      扫描本机目录中的夹具文件（.json / .jsonl / .xml），生成采集任务与文件清单；
      每个采集成功的文件会作为临时源进入既有摄取链路，业务键去重与同键非键冲突隔离沿用底座规则。
    </p>

    <div class="panel">
      <label>
        目录
        <input v-model="directory" style="width: 20rem" placeholder="fixtures 或 absolute path" />
      </label>
      <label style="margin-left: 0.75rem">
        <input type="checkbox" v-model="recursive" /> 递归扫描
      </label>
      <label style="margin-left: 0.75rem">
        <input type="checkbox" v-model="ingest" /> 采集后自动摄取
      </label>
      <label style="margin-left: 0.75rem">
        模式
        <select v-model="mode">
          <option value="incremental">incremental</option>
          <option value="full">full</option>
        </select>
      </label>
      <button style="margin-left: 0.75rem" :disabled="busy" @click="runHarvest">
        {{ busy ? '采集中…' : '发起巡检采集' }}
      </button>
      <button class="secondary" style="margin-left: 0.75rem" :disabled="busy" @click="refresh">刷新任务</button>
    </div>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>

    <div class="panel">
      <h3>采集任务</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>目录</th><th>状态</th><th>发现</th><th>成功采集</th><th>失败</th>
            <th>解析条目</th><th>摄取 parsed</th><th>写入</th><th>冲突</th><th>跳过</th>
            <th>Canonical Δ</th><th>时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>{{ t.id }}</td>
            <td class="mono">{{ t.directory }}</td>
            <td>
              <span class="tag" :class="t.status === 'ok' ? 'ok' : (t.status === 'partial' ? 'warn' : 'danger')">
                {{ t.status }}
              </span>
            </td>
            <td>{{ t.discovered_count }}</td>
            <td>{{ t.harvested_count }}</td>
            <td>{{ t.failed_count }}</td>
            <td>{{ t.parsed_items_count }}</td>
            <td>{{ t.report?.ingest?.parsed_count ?? '—' }}</td>
            <td>{{ t.report?.ingest?.upserted_count ?? '—' }}</td>
            <td>{{ t.report?.ingest?.conflict_count ?? '—' }}</td>
            <td>{{ t.report?.ingest?.skipped_count ?? '—' }}</td>
            <td>{{ t.report?.ingest?.canonical_delta ?? '—' }}</td>
            <td class="mono">{{ t.created_at }}</td>
            <td><button class="secondary" @click="openTask(t.id)">详情</button></td>
          </tr>
        </tbody>
      </table>
      <p v-if="!tasks.length" class="muted">暂无采集任务，点上方“发起巡检采集”。</p>
    </div>

    <template v-if="detail">
      <div class="panel">
        <h3>任务 #{{ detail.id }} · 对账</h3>
        <p class="muted mono">{{ detail.report?.directory }} · mode={{ detail.report?.mode }}</p>
        <div class="tiles">
          <div class="tile"><div class="hero-num">{{ detail.discovered_count }}</div><div class="muted">发现文件</div></div>
          <div class="tile"><div class="hero-num">{{ detail.harvested_count }}</div><div class="muted">成功采集</div></div>
          <div class="tile"><div class="hero-num">{{ detail.failed_count }}</div><div class="muted">采集失败</div></div>
          <div class="tile"><div class="hero-num">{{ detail.parsed_items_count }}</div><div class="muted">解析条目</div></div>
          <div class="tile"><div class="hero-num">{{ ingestReport.canonical_delta ?? '—' }}</div><div class="muted">Canonical Δ</div></div>
          <div class="tile"><div class="hero-num">{{ ingestReport.run_count ?? 0 }}</div><div class="muted">摄取 Runs</div></div>
        </div>
        <p>
          摄取摘要：parsed {{ ingestReport.parsed_count ?? 0 }} /
          upserted {{ ingestReport.upserted_count ?? 0 }}
          （insert {{ ingestReport.inserted_count ?? 0 }} · update {{ ingestReport.updated_count ?? 0 }}）/
          conflict {{ ingestReport.conflict_count ?? 0 }} /
          skipped {{ ingestReport.skipped_count ?? 0 }} ·
          staging {{ ingestReport.staging_count ?? 0 }} 行
        </p>
        <p class="mono muted">
          Canonical {{ ingestReport.canonical_count_before ?? detail.canonical_count_before }} →
          {{ ingestReport.canonical_count_after ?? detail.canonical_count_after }} ·
          ignored {{ detail.ignored_count }} · ingest status {{ ingestReport.status ?? 'not_run' }}
        </p>
        <table>
          <thead><tr><th>对账项</th><th>结果</th><th>值</th></tr></thead>
          <tbody>
            <tr v-for="[k, v] in reconRows" :key="k">
              <td class="mono">{{ k }}</td>
              <td><span class="tag" :class="checkTag(v)">{{ checkLabel(v) }}</span></td>
              <td class="mono">{{ v === null ? '—' : v }}</td>
            </tr>
          </tbody>
        </table>
        <button class="secondary" style="margin-top: 0.75rem" :disabled="busy" @click="ingestNow">
          对该任务重新摄取
        </button>
      </div>

      <div class="panel">
        <h3>文件清单</h3>
        <table>
          <thead>
            <tr>
              <th>#</th><th>相对路径</th><th>格式</th><th>采集</th><th>解析条目</th>
              <th>摄取</th><th>run</th><th>错误</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in detail.files" :key="f.id">
              <td>{{ f.id }}</td>
              <td class="mono">{{ f.relative_path }}</td>
              <td class="mono">{{ f.format }}</td>
              <td>
                <span class="tag" :class="f.parse_status === 'harvested' ? 'ok' : 'danger'">
                  {{ f.parse_status }}
                </span>
              </td>
              <td>{{ f.parsed_count }}</td>
              <td>
                <span class="tag" :class="f.ingest_status === 'ok' ? 'ok' : (f.ingest_status === 'not_run' ? 'warn' : 'danger')">
                  {{ f.ingest_status }}
                </span>
              </td>
              <td>{{ f.run_id ?? '—' }}</td>
              <td class="mono danger">{{ f.error || f.ingest_error || '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h3>摄取 Runs（与运行台同源）</h3>
        <table>
          <thead>
            <tr>
              <th>Run</th><th>源</th><th>状态</th><th>parsed</th><th>upserted</th>
              <th>conflict</th><th>skipped</th><th>canonical_count</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in detail.runs" :key="r.id">
              <td>{{ r.id }}</td>
              <td>{{ r.source_name }}</td>
              <td><span class="tag" :class="r.status === 'ok' ? 'ok' : 'danger'">{{ r.status }}</span></td>
              <td>{{ r.parsed_count }}</td>
              <td>{{ r.upserted_count }}</td>
              <td>{{ r.conflict_count }}</td>
              <td>{{ r.skipped_count }}</td>
              <td>{{ r.report?.canonical_count ?? '—' }}</td>
              <td class="mono">{{ r.created_at }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted">也可在 <router-link to="/workbench">运行台</router-link> 查看同一批 Run。</p>
      </div>
    </template>
  </div>
</template>
