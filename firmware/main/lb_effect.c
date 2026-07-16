#include "lb_effect.h"

#include <string.h>

#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "led_strip.h"
#include "led_strip_rmt.h"
#include "led_strip_spi.h"
#include "sdkconfig.h"

static const char *TAG = "lb_effect";
static led_strip_handle_t s_side;
static led_strip_handle_t s_top;
static uint16_t s_side_count;
static uint16_t s_top_count;
static uint8_t s_brightness_cap;
static SemaphoreHandle_t s_lock;
static lb_effect_snapshot_t s_current;
static lb_effect_snapshot_t s_pending;
static int64_t s_apply_at_us;
static int64_t s_phase_origin_us;
static bool s_has_pending;

const char *lb_effect_mode_name(lb_effect_mode_t mode)
{
    switch (mode) {
        case LB_EFFECT_BLINK_RED: return "BLINK_RED";
        case LB_EFFECT_BLINK_GREEN: return "BLINK_GREEN";
        case LB_EFFECT_BLINK_BLUE: return "BLINK_BLUE";
        case LB_EFFECT_SOLID_BLUE: return "SOLID_BLUE";
        default: return "OFF";
    }
}

bool lb_effect_mode_from_name(const char *name, lb_effect_mode_t *mode)
{
    if (strcmp(name, "OFF") == 0) *mode = LB_EFFECT_OFF;
    else if (strcmp(name, "BLINK_RED") == 0) *mode = LB_EFFECT_BLINK_RED;
    else if (strcmp(name, "BLINK_GREEN") == 0) *mode = LB_EFFECT_BLINK_GREEN;
    else if (strcmp(name, "BLINK_BLUE") == 0) *mode = LB_EFFECT_BLINK_BLUE;
    else if (strcmp(name, "SOLID_BLUE") == 0) *mode = LB_EFFECT_SOLID_BLUE;
    else return false;
    return true;
}

static void render(bool illuminated)
{
    uint8_t red = 0, green = 0, blue = 0;
    uint8_t scale = s_current.actual_brightness;
    if (illuminated) {
        uint8_t value = (uint8_t)((255U * scale) / 100U);
        if (s_current.mode == LB_EFFECT_BLINK_RED) red = value;
        if (s_current.mode == LB_EFFECT_BLINK_GREEN) green = value;
        if (s_current.mode == LB_EFFECT_BLINK_BLUE || s_current.mode == LB_EFFECT_SOLID_BLUE) blue = value;
    }
    for (uint16_t i = 0; i < s_side_count; ++i) {
        led_strip_set_pixel(s_side, i, red, green, blue);
    }
    for (uint16_t i = 0; i < s_top_count; ++i) {
        led_strip_set_pixel(s_top, i, red, green, blue);
    }
    ESP_ERROR_CHECK_WITHOUT_ABORT(led_strip_refresh(s_side));
    ESP_ERROR_CHECK_WITHOUT_ABORT(led_strip_refresh(s_top));
    s_current.illuminated = illuminated;
}

static bool is_blinking(lb_effect_mode_t mode)
{
    return mode == LB_EFFECT_BLINK_RED || mode == LB_EFFECT_BLINK_GREEN || mode == LB_EFFECT_BLINK_BLUE;
}

static void effect_task(void *argument)
{
    bool last_phase = false;
    while (true) {
        int64_t now = esp_timer_get_time();
        xSemaphoreTake(s_lock, portMAX_DELAY);
        if (s_has_pending && (s_apply_at_us == 0 || now >= s_apply_at_us)) {
            s_current = s_pending;
            s_phase_origin_us = s_apply_at_us == 0 ? now : s_apply_at_us;
            s_has_pending = false;
            last_phase = false;
            render(s_current.mode != LB_EFFECT_OFF);
        }
        if (is_blinking(s_current.mode) && s_current.period_ms >= 200) {
            int64_t elapsed_ms = (now - s_phase_origin_us) / 1000;
            bool phase = (elapsed_ms % s_current.period_ms) < (s_current.period_ms / 2);
            if (phase != last_phase) {
                render(phase);
                last_phase = phase;
            }
        }
        xSemaphoreGive(s_lock);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

esp_err_t lb_effect_init(const lb_config_t *config)
{
    s_side_count = config->side_led_count;
    s_top_count = config->top_led_count;
    s_brightness_cap = config->brightness_cap;
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;

    led_strip_config_t side_config = {
        .strip_gpio_num = CONFIG_LB_SIDE_GPIO,
        .max_leds = s_side_count,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags.invert_out = false,
    };
    led_strip_spi_config_t spi_config = {
        .clk_src = SPI_CLK_SRC_DEFAULT,
        .spi_bus = SPI2_HOST,
        .flags.with_dma = true,
    };
    esp_err_t err = led_strip_new_spi_device(&side_config, &spi_config, &s_side);
    if (err != ESP_OK) return err;

    led_strip_config_t top_config = {
        .strip_gpio_num = CONFIG_LB_TOP_GPIO,
        .max_leds = s_top_count,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags.invert_out = false,
    };
    led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
        .flags.with_dma = false,
    };
    err = led_strip_new_rmt_device(&top_config, &rmt_config, &s_top);
    if (err != ESP_OK) return err;

    memset(&s_current, 0, sizeof(s_current));
    s_current.requested_brightness = 1;
    render(false);
    if (xTaskCreate(effect_task, "lb_effect", 4096, NULL, 6, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    ESP_LOGI(TAG, "LED outputs ready: side=%u on GPIO%d, top=%u on GPIO%d",
             s_side_count, CONFIG_LB_SIDE_GPIO, s_top_count, CONFIG_LB_TOP_GPIO);
    return ESP_OK;
}

esp_err_t lb_effect_schedule(lb_effect_mode_t mode, uint16_t period_ms,
                             uint8_t brightness, int64_t apply_local_us)
{
    if (brightness < 1 || brightness > 100) return ESP_ERR_INVALID_ARG;
    if (is_blinking(mode) && (period_ms < 200 || period_ms > 10000)) return ESP_ERR_INVALID_ARG;
    if (!is_blinking(mode)) period_ms = 0;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_pending.mode = mode;
    s_pending.period_ms = period_ms;
    s_pending.requested_brightness = brightness;
    s_pending.actual_brightness = mode == LB_EFFECT_OFF ? 0 :
                                  (brightness < s_brightness_cap ? brightness : s_brightness_cap);
    s_pending.illuminated = false;
    s_apply_at_us = mode == LB_EFFECT_OFF ? 0 : apply_local_us;
    s_has_pending = true;
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

void lb_effect_force_off(void)
{
    if (!s_lock) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_has_pending = false;
    s_current.mode = LB_EFFECT_OFF;
    s_current.period_ms = 0;
    s_current.requested_brightness = 1;
    s_current.actual_brightness = 0;
    render(false);
    xSemaphoreGive(s_lock);
}

lb_effect_snapshot_t lb_effect_snapshot(void)
{
    lb_effect_snapshot_t result = {0};
    if (!s_lock) return result;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    result = s_current;
    xSemaphoreGive(s_lock);
    return result;
}
