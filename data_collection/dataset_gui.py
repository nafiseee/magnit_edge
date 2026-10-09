import json
import subprocess
import time
import csv
import os
from flask import Flask, request, jsonify




app = Flask(__name__)
current_gesture_id = 0

if os.path.isfile('dataset_mobile_v2.csv'):
    with open('dataset_mobile_v2.csv', 'r') as f:
        lines = f.readlines()[1:] 
        if lines:
            last_line = lines[-1].strip().split(',')
            if len(last_line) >= 5:
                current_gesture_id = int(last_line[4])

HTML_UI = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #111; color: white; font-family: sans-serif; text-align: center; padding-top: 10px; margin: 0; }
        .btn { width: 90%; height: 70px; font-size: 20px; margin: 8px; border-radius: 12px; border: none; font-weight: bold; }
        .btn-g1 { background: #ff4757; color: white; }
        .btn-g2 { background: #2ed573; color: white; }
        .btn-noise { background: #576574; color: white; }
        .btn-save { background: #1e90ff; color: white; width: 40%; }
        .btn-cancel { background: #ff6b81; color: white; width: 40%; }
        
        #status { font-size: 18px; margin: 15px; color: #eccc68; min-height: 25px; }
        #review-panel { display: none; margin-top: 15px; padding: 10px; background: #222; border-radius: 15px; }
        #controls { display: block; }
        canvas { max-width: 100%; height: 250px !important; }
    </style>
</head>
<body>
    <h2>Сборщик Жестов v6 (Sync Audio)</h2>
    <div id="status">Готов. Выбери класс:</div>
    
    <div id="controls">
        <button class="btn btn-g1" onclick="record(1)">🔴 ЖЕСТ 1</button>
        <button class="btn btn-g2" onclick="record(2)">🟢 ЖЕСТ 2</button>
        <button class="btn btn-noise" onclick="record(0)">⚪ ФОН (Шум)</button>
    </div>

    <div id="review-panel">
        <canvas id="chart"></canvas>
        <br>
        <button class="btn btn-cancel" onclick="cancel()">❌ Отмена</button>
        <button class="btn btn-save" onclick="save()">💾 Сохранить</button>
    </div>

    <script>
        let currentData = null;
        let chartInstance = null;
        
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

        function beep(freq, duration) {
            if (audioCtx.state === 'suspended') audioCtx.resume();
            
            let oscillator = audioCtx.createOscillator();
            let gainNode = audioCtx.createGain();
            
            oscillator.type = 'sine'; 
            oscillator.frequency.value = freq;
            
            gainNode.gain.setValueAtTime(1, audioCtx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration / 1000);
            
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            
            oscillator.start();
            setTimeout(() => { oscillator.stop(); }, duration);
        }

        function record(label) {
            // Разблокируем аудиоконтекст прямо по клику (требование Safari/Chrome)
            if (audioCtx.state === 'suspended') audioCtx.resume();
            
            let status = document.getElementById('status');
            document.getElementById('controls').style.display = 'none';
            document.getElementById('review-panel').style.display = 'none';
            
            status.innerText = 'Подготовка 1 сек... Замри!';
            
            // Ждем ровно 1 секунду ПЕРЕД началом записи
            setTimeout(() => {
                // Писк старта и мгновенный запрос на сервер
                beep(400, 150);
                status.innerText = 'Пишем! Делай жест!';
                
                fetch('/record/' + label)
                    .then(response => response.json())
                    .then(data => {
                        // Писк финиша
                        beep(800, 100);
                        setTimeout(() => beep(800, 100), 150);
                        
                        if(data.length === 0) {
                            status.innerText = 'Ошибка: Пустые данные от сенсора!';
                            document.getElementById('controls').style.display = 'block';
                            return;
                        }
                        currentData = data;
                        status.innerText = 'График готов. Сохраняем?';
                        document.getElementById('review-panel').style.display = 'block';
                        drawChart(data);
                    })
                    .catch(err => {
                        status.innerText = 'Ошибка сервера или сенсора!';
                        document.getElementById('controls').style.display = 'block';
                    });
            }, 1000); // 1000 мс = 1 секунда ожидания
        }

        function save() {
            fetch('/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(currentData)
            }).then(response => response.text())
            .then(text => {
                document.getElementById('status').innerText = text;
                resetUI();
            });
        }

        function cancel() {
            document.getElementById('status').innerText = 'Отменено. Пишем заново.';
            resetUI();
        }

        function resetUI() {
            document.getElementById('review-panel').style.display = 'none';
            document.getElementById('controls').style.display = 'block';
            currentData = null;
        }

        function drawChart(data) {
            let ctx = document.getElementById('chart').getContext('2d');
            if(chartInstance) chartInstance.destroy();
            
            let labels = Array.from({length: data.length}, (_, i) => i);
            let xData = data.map(d => d.x);
            let yData = data.map(d => d.y);
            let zData = data.map(d => d.z);

            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'X', data: xData, borderColor: '#ff4757', borderWidth: 2, pointRadius: 0 },
                        { label: 'Y', data: yData, borderColor: '#2ed573', borderWidth: 2, pointRadius: 0 },
                        { label: 'Z', data: zData, borderColor: '#1e90ff', borderWidth: 2, pointRadius: 0 }
                    ]
                },
                options: { animation: false, scales: { x: { display: false } } }
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return HTML_UI

@app.route('/record/<int:label>')
def record_gesture(label):
    
    magnet_path = "/data/data/com.termux/files/home/magnet"
    
    process = subprocess.Popen(
        ['su', '-c', magnet_path], 
        stdout=subprocess.PIPE, text=True
    )
    
    collected_points = []
    try:
        for line in iter(process.stdout.readline, ''):
            parts = line.split()
            if len(parts) == 4:
                try:
                    x = float(parts[1])
                    y = float(parts[2])
                    z = float(parts[3])
                    collected_points.append({'x': x, 'y': y, 'z': z, 'label': label})
                except ValueError:
                    pass
                    
            if len(collected_points) >= 100:
                break
    finally:
        process.terminate()
        subprocess.run(['su', '-c', 'killall magnet'], capture_output=True)
        
    return jsonify(collected_points)

@app.route('/save', methods=['POST'])
def save_data():
    global current_gesture_id
    current_gesture_id += 1
    
    data = request.json
    if not data:
        return "Ошибка данных", 400
        
    file_exists = os.path.isfile('dataset_mobile_v2.csv')
    with open('dataset_mobile_v2.csv', 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['x', 'y', 'z', 'label', 'gesture_id'])
        for p in data:
            writer.writerow([p['x'], p['y'], p['z'], p['label'], current_gesture_id])
            
    return f"✅ Жест #{current_gesture_id} сохранен!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)