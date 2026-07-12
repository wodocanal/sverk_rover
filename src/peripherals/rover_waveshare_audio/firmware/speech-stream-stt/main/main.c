#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "driver/usb_serial_jtag.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "bsp_board.h"
#include "rgb_led_driver.h"
#include "tca9555_driver.h"

#define PCM_SAMPLE_RATE          16000
#define PCM_FRAME_SAMPLES        320
#define PCM_INPUT_CHANNELS       4
#define STREAM_TASK_STACK_WORDS  4096
#define STREAM_TASK_PRIORITY     5
#define STREAM_MAGIC             0x314D4350u  /* "PCM1" little-endian */
#define PTT_BUTTON_MASK          IO_EXPANDER_PIN_NUM_10
#define PTT_RELEASE_GRACE_MS     2000

static const char *TAG = "pcm_stream";

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t sample_rate;
    uint16_t sample_count;
    uint32_t sequence;
} pcm_frame_header_t;

static int usb_stream_write_all(const void *src, size_t size, TickType_t ticks_to_wait)
{
    const uint8_t *cursor = (const uint8_t *)src;
    size_t remaining = size;

    while (remaining > 0) {
        int written = usb_serial_jtag_write_bytes(cursor, remaining, ticks_to_wait);
        if (written <= 0) {
            break;
        }
        cursor += written;
        remaining -= written;
    }

    return (int)(size - remaining);
}

static void usb_stream_init(void)
{
    if (!usb_serial_jtag_is_driver_installed()) {
        usb_serial_jtag_driver_config_t config = {
            .tx_buffer_size = 2048,
            .rx_buffer_size = 256,
        };
        ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    }
}

static void send_stream_banner(void)
{
    static const char banner[] =
        "\nPCM_STREAM_READY v1 sr=16000 mono=s16le frame=320 format=framed\n";
    usb_stream_write_all(banner, sizeof(banner) - 1, pdMS_TO_TICKS(20));
}

static bool is_ptt_button_pressed(void)
{
    /* User button on the TCA9555 is active low. */
    return !Read_EXIO(PTT_BUTTON_MASK);
}

static bool should_stream_audio(void)
{
    static int64_t stream_active_until_us = 0;
    int64_t now_us = esp_timer_get_time();

    if (is_ptt_button_pressed()) {
        stream_active_until_us = now_us + (PTT_RELEASE_GRACE_MS * 1000LL);
        return true;
    }

    return now_us < stream_active_until_us;
}

static void update_stream_indicator(bool usb_connected, bool stream_enabled)
{
    typedef enum {
        STREAM_INDICATOR_DISCONNECTED = 0,
        STREAM_INDICATOR_READY,
        STREAM_INDICATOR_ACTIVE,
    } stream_indicator_state_t;

    static stream_indicator_state_t last_state = -1;
    stream_indicator_state_t next_state = STREAM_INDICATOR_DISCONNECTED;

    if (!usb_connected) {
        next_state = STREAM_INDICATOR_DISCONNECTED;
    } else if (stream_enabled) {
        next_state = STREAM_INDICATOR_ACTIVE;
    } else {
        next_state = STREAM_INDICATOR_READY;
    }

    if (next_state == last_state) {
        return;
    }

    switch (next_state) {
        case STREAM_INDICATOR_DISCONNECTED:
            set_rgb_color(RGB_COLOR_WHITE);
            set_rgb_mode(RGB_MODE_IDLE);
            break;
        case STREAM_INDICATOR_READY:
            set_rgb_color(RGB_COLOR_WHITE);
            set_rgb_mode(RGB_MODE_IDLE);
            break;
        case STREAM_INDICATOR_ACTIVE:
            set_rgb_color(RGB_COLOR_GREEN);
            set_rgb_mode(RGB_MODE_REC_COMMAND);
            break;
    }

    last_state = next_state;
}

static inline int16_t mix_mics_to_mono(const int16_t *raw_frame, size_t index)
{
    int32_t mic_left = raw_frame[index * PCM_INPUT_CHANNELS + 1];
    int32_t mic_right = raw_frame[index * PCM_INPUT_CHANNELS + 3];
    int32_t mixed = (mic_left + mic_right) / 2;
    if (mixed > INT16_MAX) {
        mixed = INT16_MAX;
    } else if (mixed < INT16_MIN) {
        mixed = INT16_MIN;
    }
    return (int16_t)mixed;
}

static void pcm_stream_task(void *arg)
{
    size_t raw_bytes = PCM_FRAME_SAMPLES * PCM_INPUT_CHANNELS * sizeof(int16_t);
    int16_t *raw = heap_caps_malloc(raw_bytes, MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    int16_t *mono = heap_caps_malloc(PCM_FRAME_SAMPLES * sizeof(int16_t), MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    uint32_t sequence = 0;
    bool banner_sent = false;

    if (!raw || !mono) {
        ESP_LOGE(TAG, "Failed to allocate audio buffers");
        vTaskDelete(NULL);
        return;
    }

    for (;;) {
        bool usb_connected = usb_serial_jtag_is_connected();
        if (!usb_connected) {
            banner_sent = false;
            update_stream_indicator(false, false);
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        if (!banner_sent) {
            send_stream_banner();
            banner_sent = true;
        }

        ESP_ERROR_CHECK(esp_get_feed_data(true, raw, raw_bytes));
        bool stream_enabled = should_stream_audio();
        update_stream_indicator(true, stream_enabled);
        if (!stream_enabled) {
            continue;
        }

        for (size_t i = 0; i < PCM_FRAME_SAMPLES; ++i) {
            mono[i] = mix_mics_to_mono(raw, i);
        }

        pcm_frame_header_t header = {
            .magic = STREAM_MAGIC,
            .sample_rate = PCM_SAMPLE_RATE,
            .sample_count = PCM_FRAME_SAMPLES,
            .sequence = sequence++,
        };

        int header_written = usb_stream_write_all(&header, sizeof(header), 0);
        int payload_written = usb_stream_write_all(mono, PCM_FRAME_SAMPLES * sizeof(int16_t), 0);

        if (header_written != sizeof(header) || payload_written != PCM_FRAME_SAMPLES * (int)sizeof(int16_t)) {
            vTaskDelay(pdMS_TO_TICKS(5));
        }
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(esp_board_init(PCM_SAMPLE_RATE, 2, 16));
    tca9555_driver_init();
    RGB_Example();
    set_rgb_color(RGB_COLOR_WHITE);
    set_rgb_mode(RGB_MODE_IDLE);
    usb_stream_init();

    ESP_LOGI(TAG, "Starting PCM stream task");
    ESP_LOGI(TAG, "Output: 16 kHz mono s16le over USB serial");
    ESP_LOGI(TAG, "Frame size: %d samples", PCM_FRAME_SAMPLES);
    ESP_LOGI(TAG, "Push-to-talk: hold user button on EXIO10, release grace: %d ms", PTT_RELEASE_GRACE_MS);

    xTaskCreatePinnedToCore(pcm_stream_task, "pcm_stream", STREAM_TASK_STACK_WORDS, NULL, STREAM_TASK_PRIORITY, NULL, 1);
}
