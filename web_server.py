"""
Flask web server to display BME280 sensor data.
"""

from flask import Flask, jsonify, render_template_string, request
from database import get_readings, get_readings_since, get_latest_reading

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BME280 Sensor Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }
        h1 { text-align: center; margin-bottom: 20px; color: #fff; }
        .current-values {
            display: flex;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
            margin-bottom: 30px;
        }
        .value-card {
            background: #16213e;
            border-radius: 10px;
            padding: 20px 30px;
            text-align: center;
            min-width: 150px;
        }
        .value-card .label { font-size: 14px; color: #888; }
        .value-card .value { font-size: 32px; font-weight: bold; margin: 10px 0; }
        .value-card.temp .value { color: #ff6b6b; }
        .value-card.humidity .value { color: #4ecdc4; }
        .value-card.pressure .value { color: #ffe66d; }
        .chart-container {
            background: #16213e;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .chart-container canvas { max-height: 250px; }
        .time-buttons {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 20px;
        }
        .time-btn {
            background: #16213e;
            border: 2px solid #333;
            color: #fff;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        .time-btn:hover { background: #1f3460; }
        .time-btn.active { border-color: #4ecdc4; background: #1f3460; }
        .reset-zoom {
            background: #16213e;
            border: 2px solid #ff6b6b;
            color: #ff6b6b;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            margin-left: auto;
        }
        .reset-zoom:hover { background: #2a1a1a; }
        .chart-header {
            display: flex;
            justify-content: flex-end;
            margin-bottom: 10px;
        }
        .zoom-hint {
            color: #666;
            font-size: 11px;
            text-align: center;
            margin-bottom: 15px;
        }
        .updated { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>BME280 Sensor Dashboard</h1>

    <div class="time-buttons">
        <button class="time-btn" data-hours="1">1 Hour</button>
        <button class="time-btn" data-hours="6">6 Hours</button>
        <button class="time-btn active" data-hours="24">24 Hours</button>
        <button class="time-btn" data-hours="168">7 Days</button>
        <button class="time-btn" data-hours="720">30 Days</button>
    </div>

    <div class="current-values">
        <div class="value-card temp">
            <div class="label">Temperature</div>
            <div class="value" id="temp">--</div>
            <div class="label">°C</div>
        </div>
        <div class="value-card humidity">
            <div class="label">Humidity</div>
            <div class="value" id="humidity">--</div>
            <div class="label">%</div>
        </div>
        <div class="value-card pressure">
            <div class="label">Pressure</div>
            <div class="value" id="pressure">--</div>
            <div class="label">hPa</div>
        </div>
    </div>

    <div class="zoom-hint">Drag to zoom | Scroll to zoom | Double-click to reset</div>

    <div class="chart-container">
        <div class="chart-header"><button class="reset-zoom" onclick="tempChart.resetZoom()">Reset Zoom</button></div>
        <canvas id="tempChart"></canvas>
    </div>
    <div class="chart-container">
        <div class="chart-header"><button class="reset-zoom" onclick="humidityChart.resetZoom()">Reset Zoom</button></div>
        <canvas id="humidityChart"></canvas>
    </div>
    <div class="chart-container">
        <div class="chart-header"><button class="reset-zoom" onclick="pressureChart.resetZoom()">Reset Zoom</button></div>
        <canvas id="pressureChart"></canvas>
    </div>

    <div class="updated">Last updated: <span id="lastUpdate">--</span></div>

    <script>
        const chartOptions = {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                zoom: {
                    zoom: {
                        wheel: { enabled: true },
                        drag: { enabled: true, backgroundColor: 'rgba(78, 205, 196, 0.2)', borderColor: '#4ecdc4', borderWidth: 1 },
                        pinch: { enabled: true },
                        mode: 'x',
                        onZoomComplete: () => {}
                    },
                    pan: { enabled: true, mode: 'x' }
                }
            },
            scales: {
                x: { ticks: { color: '#888', maxTicksLimit: 10 }, grid: { color: '#333' } },
                y: { ticks: { color: '#888' }, grid: { color: '#333' } }
            }
        };

        const tempChart = new Chart(document.getElementById('tempChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Temperature (°C)', data: [], borderColor: '#ff6b6b', tension: 0.3 }] },
            options: { ...chartOptions, plugins: { ...chartOptions.plugins, title: { display: true, text: 'Temperature (°C)', color: '#fff' } } }
        });

        const humidityChart = new Chart(document.getElementById('humidityChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Humidity (%)', data: [], borderColor: '#4ecdc4', tension: 0.3 }] },
            options: { ...chartOptions, plugins: { ...chartOptions.plugins, title: { display: true, text: 'Humidity (%)', color: '#fff' } } }
        });

        const pressureChart = new Chart(document.getElementById('pressureChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Pressure (hPa)', data: [], borderColor: '#ffe66d', tension: 0.3 }] },
            options: { ...chartOptions, plugins: { ...chartOptions.plugins, title: { display: true, text: 'Pressure (hPa)', color: '#fff' } } }
        });

        let currentHours = 24;

        async function updateData() {
            try {
                const response = await fetch(`/api/readings?hours=${currentHours}`);
                const data = await response.json();

                if (data.latest) {
                    document.getElementById('temp').textContent = data.latest.temperature.toFixed(1);
                    document.getElementById('humidity').textContent = data.latest.humidity.toFixed(1);
                    document.getElementById('pressure').textContent = data.latest.pressure.toFixed(1);
                }

                const labels = data.history.map(r => {
                    const d = new Date(r.timestamp);
                    if (currentHours <= 24) {
                        return d.toLocaleTimeString();
                    } else {
                        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                    }
                });

                tempChart.data.labels = labels;
                tempChart.data.datasets[0].data = data.history.map(r => r.temperature);
                tempChart.update();

                humidityChart.data.labels = labels;
                humidityChart.data.datasets[0].data = data.history.map(r => r.humidity);
                humidityChart.update();

                pressureChart.data.labels = labels;
                pressureChart.data.datasets[0].data = data.history.map(r => r.pressure);
                pressureChart.update();

                document.getElementById('lastUpdate').textContent = new Date().toLocaleString();
            } catch (err) {
                console.error('Failed to fetch data:', err);
            }
        }

        // Time range button handlers
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentHours = parseInt(btn.dataset.hours);
                updateData();
            });
        });

        updateData();
        setInterval(updateData, 10000);  // Update every 10 seconds
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/readings')
def api_readings():
    hours = request.args.get('hours', default=24, type=int)
    history = get_readings_since(hours)
    latest = get_latest_reading()

    return jsonify({
        'latest': {
            'timestamp': latest[0],
            'temperature': latest[1],
            'humidity': latest[2],
            'pressure': latest[3]
        } if latest else None,
        'history': [
            {'timestamp': r[0], 'temperature': r[1], 'humidity': r[2], 'pressure': r[3]}
            for r in history
        ]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
