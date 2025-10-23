// === helpers ================================================================

function clamp01(x) { return Math.max(0, Math.min(100, x)); }
function safeNum(v, def = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}
function kbpsFmt(v) {
  const n = safeNum(v, 0);
  if (n >= 1024) return (n / 1024).toFixed(1) + ' MB/s';
  return n.toFixed(0) + ' KB/s';
}

// Persist last N points for a chart by label (sessionStorage)
function loadSeries(label, n = 30) {
  const saved = sessionStorage.getItem(label);
  const arr = saved ? JSON.parse(saved) : Array(n).fill(0);
  return Array.isArray(arr) ? arr.slice(-n) : Array(n).fill(0);
}
function saveSeries(label, data) {
  sessionStorage.setItem(label, JSON.stringify(data));
}

// === chart factories ========================================================

function createPercentChart(ctx, label, color) {
  const data = loadSeries(label);
  const h = ctx.canvas.clientHeight || 100;
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, color + '33');
  g.addColorStop(1, color + '00');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array(data.length).fill(''),
      datasets: [{
        label,
        data,
        borderColor: color,
        backgroundColor: g,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.35,
        fill: true,
        cubicInterpolationMode: 'monotone'
      }]
    },
    options: {
      responsive: true,
      animation: false,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { line: { borderCapStyle: 'round', borderJoinStyle: 'round' } },
      scales: {
        y: {
          beginAtZero: true,
          min: 0,
          max: 100,
          ticks: {
            maxTicksLimit: 5,
            callback: v => v + '%',
            color: '#8fa3b8',
            font: { family: "'Segoe UI', sans-serif", size: 10 }
          },
          grid: { color: 'rgba(148,163,184,.15)', drawBorder: false }
        },
        x: { ticks: { display: false }, grid: { display: false } }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          backgroundColor: 'rgba(17,17,17,.9)',
          borderColor: 'rgba(148,163,184,.25)',
          borderWidth: 1,
          titleColor: '#e5e7eb',
          bodyColor: '#e5e7eb',
          padding: 8
        }
      }
    }
  });
}

function createNetworkChart(ctx, label, color) {
  const data = loadSeries(label);
  const h = ctx.canvas.clientHeight || 100;
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, color + '33');
  g.addColorStop(1, color + '00');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array(data.length).fill(''),
      datasets: [{
        label,
        data,
        borderColor: color,
        backgroundColor: g,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.35,
        fill: true,
        cubicInterpolationMode: 'monotone'
      }]
    },
    options: {
      responsive: true,
      animation: false,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { line: { borderCapStyle: 'round', borderJoinStyle: 'round' } },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            maxTicksLimit: 5,
            callback: kbpsFmt,
            color: '#8fa3b8',
            font: { family: "'Segoe UI', sans-serif", size: 10 }
          },
          grid: { color: 'rgba(148,163,184,.15)', drawBorder: false }
        },
        x: { ticks: { display: false }, grid: { display: false } }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          backgroundColor: 'rgba(17,17,17,.9)',
          borderColor: 'rgba(148,163,184,.25)',
          borderWidth: 1,
          titleColor: '#e5e7eb',
          bodyColor: '#e5e7eb',
          padding: 8
        }
      }
    }
  });
}

// === initialize charts ======================================================

const cpuChart = createPercentChart(
  document.getElementById('cpuChart').getContext('2d'), 'CPU %', '#2196F3'
);
const ramChart = createPercentChart(
  document.getElementById('ramChart').getContext('2d'), 'RAM %', '#00BCD4'
);
const diskChart = createPercentChart(
  document.getElementById('diskChart').getContext('2d'), 'Disk %', '#FF9800'
);
const netChart = createNetworkChart(
  document.getElementById('netChart').getContext('2d'), 'Network', '#4CAF50'
);

// === update helpers =========================================================

function updateChart(chart, value, labelForStorage) {
  const v = safeNum(value, 0);
  const ds = chart.data.datasets[0];

  ds.data.push(v);
  chart.data.labels.push('');
  if (ds.data.length > 30) {
    ds.data.shift();
    chart.data.labels.shift();
  }
  saveSeries(labelForStorage ?? ds.label, ds.data);

  // For network, nudge suggestedMax to keep the line nicely visible
  if (chart === netChart) {
    const maxV = Math.max(...ds.data, 10);
    chart.options.scales.y.suggestedMax = maxV * 1.2; // headroom
  }

  chart.update('none');
}

function updateProgressBar(id, percent) {
  const bar = document.getElementById(id);
  if (bar) bar.style.width = `${clamp01(safeNum(percent, 0))}%`;
}

function updateTextValues(data) {
  // CPU
  document.getElementById('cpuInfo').innerHTML = `
    <div class="title">CPU:</div>
    <div class="value">${safeNum(data.cpu, 0)}%</div>
    <div>${data.cpu_name || 'Unknown CPU'}</div>
    <div>${(data.cpu_cores ?? '?')} kerner, ${data.cpu_freq || '? / ? GHz'}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="cpuBar"></div></div>`;
  updateProgressBar('cpuBar', data.cpu);

  // RAM
  document.getElementById('ramInfo').innerHTML = `
    <div class="title">RAM:</div>
    <div class="value">${safeNum(data.ram, 0)}%</div>
    <div>Total: ${data.ram_total ?? '?'} MB</div>
    <div>Fri: ${data.ram_free ?? '?'} MB</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="ramBar"></div></div>`;
  updateProgressBar('ramBar', data.ram);

  // Disk
  document.getElementById('diskInfo').innerHTML = `
    <div class="title">Disk:</div>
    <div class="value">${safeNum(data.disk, 0)}%</div>
    <div>Brug: ${data.disk_used ?? '?'} / ${data.disk_total ?? '?'}</div>
    <div>Fri: ${data.disk_free ?? '?'}</div>
    <div>Model: ${data.disk_model || "?"} (${data.disk_device || "?"})</div>
    <div>Temp: ${(data.disk_temp && data.disk_temp !== "?") ? (data.disk_temp + " °C") : "?"}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="diskBar"></div></div>`;
  updateProgressBar('diskBar', data.disk);

  // Network (text)
  const totalKBs = safeNum(data.network, 0);
  document.getElementById('netInfo').innerHTML = `
    <div class="title">Network:</div>
    <div class="value">${kbpsFmt(totalKBs)}</div>
    <div>⬇ ${kbpsFmt(data.net_rx)} , ⬆ ${kbpsFmt(data.net_tx)}</div>
    <div>Interface: ${data.net_iface || '?'}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="netBar"></div></div>`;
  updateProgressBar('netBar', Math.min(totalKBs, 100));

  // Uptime + CPU temp
  document.getElementById('uptimeInfo').innerHTML = `
    <div class="title">System Uptime:</div>
    <div class="value">${data.uptime || '--'}</div>`;
  document.getElementById('tempInfo').innerHTML = `
    <div class="title">CPU Temp:</div>
    <div class="value">${(data.cpu_temp ?? '--')} °C</div>`;
}

// === data loop =============================================================

async function fetchData() {
  try {
    const res = await fetch('/metrics');
    const data = await res.json();
    if (data == null || typeof data.cpu !== 'number') return;

    updateChart(cpuChart, data.cpu, 'CPU %');
    updateChart(ramChart, data.ram, 'RAM %');
    updateChart(diskChart, data.disk, 'Disk %');
    updateChart(netChart, data.network, 'Network');

    updateTextValues(data);
    sessionStorage.setItem('latest_metrics', JSON.stringify(data));
  } catch (err) {
    console.error('Error fetching data:', err);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  // ?reset=true clears cached series
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('reset') === 'true') {
    sessionStorage.clear();
    for (const c of [cpuChart, ramChart, diskChart, netChart]) {
      c.data.datasets[0].data = [];
      c.data.labels = [];
      c.update();
    }
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  // Restore last metrics for the boxes (optional)
  const saved = sessionStorage.getItem('latest_metrics');
  if (saved) {
    try { updateTextValues(JSON.parse(saved)); } catch { }
  }

  fetchData();
  setInterval(fetchData, 2000);
});
