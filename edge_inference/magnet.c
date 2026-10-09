#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <android/sensor.h>
#include <android/looper.h>

int main() {
    ASensorManager* sensorManager = ASensorManager_getInstance();
    if (!sensorManager) {
        printf("Ошибка: Не удалось получить ASensorManager.\n");
        return 1;
    }

    const ASensor* magnetSensor = ASensorManager_getDefaultSensor(sensorManager, ASENSOR_TYPE_MAGNETIC_FIELD);
    if (!magnetSensor) {
        printf("Ошибка: Магнитометр не найден на аппаратном уровне.\n");
        return 1;
    }

    ALooper* looper = ALooper_prepare(ALOOPER_PREPARE_ALLOW_NON_CALLBACKS);
    ASensorEventQueue* queue = ASensorManager_createEventQueue(sensorManager, looper, 1, NULL, NULL);

    if (!queue) {
        printf("Ошибка: Не удалось создать очередь событий.\n");
        return 1;
    }

    ASensorEventQueue_enableSensor(queue, magnetSensor);
    ASensorEventQueue_setEventRate(queue, magnetSensor, 10000); 

    printf("Нативный демон запущен. Ждем данные на 100 Гц...\n");

    while (1) {
        int ident;
        int events;
        void* data;
        
        // Используем pollOnce, как того требует новый Android API
        while ((ident = ALooper_pollOnce(-1, NULL, &events, &data)) >= 0) {
            if (ident == 1) {
                ASensorEvent event;
                while (ASensorEventQueue_getEvents(queue, &event, 1) > 0) {
                    if (event.type == ASENSOR_TYPE_MAGNETIC_FIELD) {
                        // Явное приведение к long long для совместимости 32/64-bit
                        printf("%lld %.2f %.2f %.2f\n", (long long)event.timestamp, event.magnetic.x, event.magnetic.y, event.magnetic.z);
                        fflush(stdout);
                    }
                }
            }
        }
    }

    return 0;
}