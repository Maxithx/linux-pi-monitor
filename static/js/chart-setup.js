function createChart(ctx, label, color) {
  const savedData = sessionStorage.getItem(label);
  const chartData = savedData ? JSON.parse(savedData) : Array(30).fill(0);

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array(chartData.length).fill(''),
      datasets: [{
        label: label,
        data: chartData,
        borderColor: color,
        backgroundColor: color + "33",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      animation: false,
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          ticks: {
            stepSize: 20,
            callback: val => val + '%',
            color: '#ccc',
            font: { family: "'Segoe UI', sans-serif" }
          },
          grid: { color: '#444' }
        },
        x: {
          ticks: { display: false },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          labels: {
            color: '#ccc',
            font: { family: "'Segoe UI', sans-serif" }
          }
        }
      }
    }
  });
}

const cpuChart = createChart(document.getElementById("cpuChart").getContext("2d"), "CPU %", "#2196F3");
const ramChart = createChart(document.getElementById("ramChart").getContext("2d"), "RAM %", "#9C27B0");
const diskChart = createChart(document.getElementById("diskChart").getContext("2d"), "Disk %", "#FF9800");
const netChart = createChart(document.getElementById("netChart").getContext("2d"), "Netværk %", "#4CAF50");

function updateChart(chart, value) {
  chart.data.datasets[0].data.push(value);
  chart.data.labels.push('');
  if (chart.data.datasets[0].data.length > 30) {
    chart.data.datasets[0].data.shift();
    chart.data.labels.shift();
  }
  sessionStorage.setItem(chart.data.datasets[0].label, JSON.stringify(chart.data.datasets[0].data));
  chart.update('none');
}

function updateProgressBar(id, percent) {
  const bar = document.getElementById(id);
  if (bar) bar.style.width = `${percent}%`;
}

function updateTextValues(data) {
  document.getElementById("cpuInfo").innerHTML = `
    <div class="title">CPU:</div>
    <div class="value">${data.cpu}%</div>
    <div>${data.cpu_name}</div>
    <div>${data.cpu_cores} kerner, ${data.cpu_freq}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="cpuBar"></div></div>`;
  updateProgressBar("cpuBar", data.cpu);

  document.getElementById("ramInfo").innerHTML = `
    <div class="title">RAM:</div>
    <div class="value">${data.ram}%</div>
    <div>Total: ${data.ram_total} MB</div>
    <div>Fri: ${data.ram_free} MB</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="ramBar"></div></div>`;
  updateProgressBar("ramBar", data.ram);

  document.getElementById("diskInfo").innerHTML = `
    <div class="title">Disk:</div>
    <div class="value">${data.disk}%</div>
    <div>Brug: ${data.disk_used} / ${data.disk_total}</div>
    <div>Fri: ${data.disk_free}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="diskBar"></div></div>`;
  updateProgressBar("diskBar", data.disk);

  document.getElementById("netInfo").innerHTML = `
    <div class="title">Netværk:</div>
    <div class="value">${data.network} KB/s</div>
    <div>⬇ ${data.net_rx} KB/s, ⬆ ${data.net_tx} KB/s</div>
    <div>Interface: ${data.net_iface}</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="netBar"></div></div>`;
  updateProgressBar("netBar", Math.min(data.network, 100));

  document.getElementById("uptimeInfo").innerHTML = `
    <div class="title">System Uptime:</div>
    <div class="value">${data.uptime}</div>`;

  document.getElementById("tempInfo").innerHTML = `
    <div class="title">CPU Temp:</div>
    <div class="value">${data.cpu_temp} °C</div>`;
}

async function fetchData() {
  try {
    const response = await fetch('/metrics');
    const data = await response.json();
    if (!data.cpu) return;

    updateChart(cpuChart, data.cpu);
    updateChart(ramChart, data.ram);
    updateChart(diskChart, data.disk);
    updateChart(netChart, data.network);
    updateTextValues(data);

    sessionStorage.setItem("latest_metrics", JSON.stringify(data));
  } catch (err) {
    console.error("Fejl ved hentning af data:", err);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('reset') === 'true') {
    sessionStorage.clear();
    cpuChart.data.datasets[0].data = [];
    ramChart.data.datasets[0].data = [];
    diskChart.data.datasets[0].data = [];
    netChart.data.datasets[0].data = [];
    cpuChart.update();
    ramChart.update();
    diskChart.update();
    netChart.update();
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  // ← Hent og vis gemte tekstdata hvis de findes
  const saved = sessionStorage.getItem("latest_metrics");
  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      updateTextValues(parsed);
    } catch (e) {
      console.warn("Gemte metrics kunne ikke parses:", e);
    }
  }

  fetchData();
  setInterval(fetchData, 2000);
});
