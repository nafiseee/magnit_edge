import subprocess
import collections
import time
import sys
import numpy as np

WINDOW_SIZE = 100
sliding_window = collections.deque(maxlen=WINDOW_SIZE)

print("Загрузка весов NumPyEdgeCNN...")
try:
    w = dict(np.load('weights.npz'))
except Exception as e:
    print(f"Ошибка загрузки weights.npz: {e}")
    sys.exit(1)

# ==========================================
# ЧИСТАЯ МАТЕМАТИКА НЕЙРОСЕТИ
# ==========================================
def relu(x): return np.maximum(0, x)

def conv1d(x, w_conv, b_conv, stride, padding):
    in_c, length = x.shape
    out_c, _, k = w_conv.shape
    x_pad = np.pad(x, ((0,0), (padding, padding)), mode='constant')
    out_len = (length + 2*padding - k) // stride + 1
    out = np.zeros((out_c, out_len))
    for i in range(out_len):
        start = i * stride
        window = x_pad[:, start:start+k]
        out[:, i] = np.sum(w_conv * window, axis=(1,2)) + b_conv
    return out

def batchnorm1d(x, w_bn, b_bn, mean, var, eps=1e-5):
    std = np.sqrt(var + eps)
    x_norm = (x - mean[:, None]) / std[:, None]
    return x_norm * w_bn[:, None] + b_bn[:, None]

def maxpool1d(x, k, stride):
    c, length = x.shape
    out_len = (length - k) // stride + 1
    out = np.zeros((c, out_len))
    for i in range(out_len):
        start = i * stride
        out[:, i] = np.max(x[:, start:start+k], axis=1)
    return out

def predict_gesture(window_data, baseline):
    # 1. Вычитаем фон и считаем нелинейную магнитуду (4-й канал)
    normalized = []
    for vx, vy, vz in window_data:
        nx = vx - baseline[0]
        ny = vy - baseline[1]
        nz = vz - baseline[2]
        mag = np.sqrt(nx**2 + ny**2 + nz**2)
        normalized.append((nx, ny, nz, mag))
    
    x = np.array(normalized, dtype=np.float32).T 
    
    # 2. Клиппинг и нормализация (защита от аномалий)
    x = np.clip(x, -500.0, 500.0) / 500.0
    
    # --- СЛОЙ 1 ---
    x = conv1d(x, w['features.0.weight'], w['features.0.bias'], stride=2, padding=2)
    x = batchnorm1d(x, w['features.1.weight'], w['features.1.bias'], w['features.1.running_mean'], w['features.1.running_var'])
    x = relu(x)
    x = maxpool1d(x, k=2, stride=2)
    
    # --- СЛОЙ 2 ---
    # ИСПРАВЛЕНО: padding=2 (как в PyTorch: nn.Conv1d(..., padding=2))
    x = conv1d(x, w['features.4.weight'], w['features.4.bias'], stride=1, padding=2)
    x = batchnorm1d(x, w['features.5.weight'], w['features.5.bias'], w['features.5.running_mean'], w['features.5.running_var'])
    x = relu(x)
    
    # ИСПРАВЛЕНО: Добавлен второй слой MaxPool (сжимаем с 26 до 13 кадров)
    x = maxpool1d(x, k=2, stride=2)
    
    # --- КЛАССИФИКАТОР ---
    # Эквивалент nn.Flatten() - вытягиваем двумерную матрицу в вектор
    x = x.flatten() 
    
    # Первый линейный слой + ReLU (принимает 416 признаков)
    x = np.dot(w['classifier.1.weight'], x) + w['classifier.1.bias'] 
    x = relu(x)
    
    # Финальный линейный слой (3 нейрона)
    logits = np.dot(w['classifier.3.weight'], x) + w['classifier.3.bias'] 
    
    # Жесткий порог уверенности (защита от фонового шума)
    if np.max(logits) < 1.5: 
        return 0
    return int(np.argmax(logits))

# ==========================================
# ИНТЕГРАЦИЯ С ЖЕЛЕЗОМ ТЕЛЕФОНА
# ==========================================
def trigger_action(gesture_class):
    # Оставляем только визуальный вывод
    if gesture_class == 1:
        return "🔴 [ <---- ВЛЕВО  ] Жест 1"
    elif gesture_class == 2:
        return "🟢 [  ВПРАВО ----> ] Жест 2"
    return ""

def main():
    is_calibrated = False
    baseline = [0.0, 0.0, 0.0] 
    
    print("[DEBUG] 1. Запускаем нативный стрим сенсора через root...")
    process = subprocess.Popen(
        ['su', '-c', './magnet'], 
        stdout=subprocess.PIPE, 
        text=True
    )
    
    try:
        for line in iter(process.stdout.readline, ''):
            parts = line.split()
            
            if len(parts) == 4:
                try:
                    raw_x = float(parts[1])
                    raw_y = float(parts[2])
                    raw_z = float(parts[3])
                except ValueError:
                    continue
                    
                sliding_window.append((raw_x, raw_y, raw_z))
                
                # --- ПЕРВИЧНАЯ КАЛИБРОВКА ---
                if len(sliding_window) == WINDOW_SIZE and not is_calibrated:
                    baseline[0] = sum(v[0] for v in sliding_window) / WINDOW_SIZE
                    baseline[1] = sum(v[1] for v in sliding_window) / WINDOW_SIZE
                    baseline[2] = sum(v[2] for v in sliding_window) / WINDOW_SIZE
                    is_calibrated = True
                    sliding_window.clear() 
                    print(f"\n[КЭШ] Стартовый фон откалиброван: X:{baseline[0]:.1f} Y:{baseline[1]:.1f} Z:{baseline[2]:.1f}")
                    continue

                if not is_calibrated:
                    sys.stdout.write(f"\r[КАЛИБРОВКА] Сбор фона: {len(sliding_window)}/100")
                    sys.stdout.flush()
                    continue
                
                # --- ИНФЕРЕНС ---
                if len(sliding_window) == WINDOW_SIZE:
                    gesture_class = predict_gesture(sliding_window, baseline)
                    
                    if gesture_class != 0:
                        action_msg = trigger_action(gesture_class)
                        print(f"\n\n[🔥] РАСПОЗНАНО: {action_msg}\n")
                        # Очищаем окно, чтобы не было повторных срабатываний подряд
                        sliding_window.clear() 
                    else:
                        # ДИНАМИЧЕСКИЙ ФОН: Если жеста нет, плавно подтягиваем фон к текущей реальности
                        baseline[0] = baseline[0] * 0.95 + raw_x * 0.05
                        baseline[1] = baseline[1] * 0.95 + raw_y * 0.05
                        baseline[2] = baseline[2] * 0.95 + raw_z * 0.05
                        
                        sys.stdout.write(f"\r[СЛУШАЮ] Жду жест... Отклонение от фона -> X: {abs(raw_x - baseline[0]):5.1f} | Y: {abs(raw_y - baseline[1]):5.1f}")
                        sys.stdout.flush()
                        
    except KeyboardInterrupt:
        print("\nОстановка движка...")
    finally:
        print("Закрываем трубу сенсора и убиваем фоновый процесс...")
        process.terminate()
        subprocess.run(['su', '-c', 'killall magnet'], capture_output=True)

if __name__ == "__main__":
    main()