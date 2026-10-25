#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "esp_https_server.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "class/hid/hid_device.h"
#include "credentials.h"
#include "lwip/sockets.h"

static const uint8_t report_desc[] = {TUD_HID_REPORT_DESC_KEYBOARD()};
static const uint8_t config_desc[] = {
    TUD_CONFIG_DESCRIPTOR(1, 1, 0, TUD_CONFIG_DESC_LEN + TUD_HID_DESC_LEN, 0, 250),
    TUD_HID_DESCRIPTOR(0, 4, HID_ITF_PROTOCOL_KEYBOARD, sizeof(report_desc), 0x81, 8, 10)
};
static const char *strings[] = {(char[]){0x09, 0x04}, "Local Recovery", "Recovery Keyboard", "S3-Recovery", "Keyboard"};
static int64_t armed_until;
static uint32_t sequence;
static uint8_t leds;
static bool release_pending;

static void discovery(void *arg) {
    (void)arg;
    int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in address = {.sin_family=AF_INET, .sin_port=htons(4210), .sin_addr.s_addr=htonl(INADDR_ANY)};
    if (fd < 0) { vTaskDelete(NULL); return; }
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0) { close(fd); vTaskDelete(NULL); return; }
    while (true) {
        char query[32];
        struct sockaddr_in peer;
        socklen_t size = sizeof(peer);
        int count = recvfrom(fd, query, sizeof(query), 0, (struct sockaddr *)&peer, &size);
        if (count == 10 && !memcmp(query, "ARCH-HID/1", 10))
            sendto(fd, "ARCH-HID/1", 10, 0, (struct sockaddr *)&peer, size);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance) { (void)instance; return report_desc; }
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, uint8_t *buf, uint16_t len) {
    (void)instance; (void)id; (void)type; (void)buf; (void)len; return 0;
}
void tud_hid_set_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, const uint8_t *buf, uint16_t len) {
    (void)instance; (void)id;
    if (type == HID_REPORT_TYPE_OUTPUT && len) leds = buf[0];
}
static bool ready(void) {
    for (int i = 0; i < 100; ++i) {
        if (tud_hid_ready()) return true;
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return false;
}
static bool release_keys(void) {
    if (!ready() || !tud_hid_keyboard_report(0, 0, NULL)) return false;
    if (!ready()) return false;
    release_pending = false;
    return true;
}
static bool authorized(httpd_req_t *req) {
    char value[80] = {0};
    const char expected[] = "Bearer " API_TOKEN;
    if (httpd_req_get_hdr_value_str(req, "Authorization", value, sizeof(value)) != ESP_OK) return false;
    unsigned diff = strlen(value) ^ (sizeof(expected) - 1);
    for (size_t i = 0; i < sizeof(expected) - 1; ++i) diff |= (unsigned char)value[i] ^ (unsigned char)expected[i];
    return diff == 0;
}
static esp_err_t fail(httpd_req_t *req, const char *status, const char *message) {
    httpd_resp_set_status(req, status);
    return httpd_resp_sendstr(req, message);
}
static esp_err_t api(httpd_req_t *req) {
    if (!authorized(req)) {
        vTaskDelay(pdMS_TO_TICKS(150));
        return fail(req, "401 Unauthorized", "Unauthorized");
    }
    if (!strcmp(req->uri, "/status")) {
        char result[160];
        snprintf(result, sizeof(result), "{\"usb\":%s,\"armed\":%s,\"sequence\":%lu,\"leds\":%u}",
            tud_mounted() ? "true" : "false", esp_timer_get_time() < armed_until ? "true" : "false",
            (unsigned long)sequence, leds);
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_sendstr(req, result);
    }
    if (!strcmp(req->uri, "/disarm")) {
        armed_until = 0;
        release_pending = true;
        release_keys();
        return httpd_resp_sendstr(req, "Disarmed");
    }
    if (!strcmp(req->uri, "/arm")) {
        if (!release_keys()) return fail(req, "503 Service Unavailable", "USB unavailable");
        armed_until = esp_timer_get_time() + 120000000;
        return httpd_resp_sendstr(req, "Armed for 120 seconds");
    }
    if (esp_timer_get_time() >= armed_until) return fail(req, "403 Forbidden", "Disarmed");
    if (req->content_len != 6) return fail(req, "400 Bad Request", "Expected 6 bytes");
    uint8_t body[6];
    size_t received = 0;
    while (received < sizeof(body)) {
        int count = httpd_req_recv(req, (char *)body + received, sizeof(body) - received);
        if (count <= 0) return ESP_FAIL;
        received += count;
    }
    uint32_t next = ((uint32_t)body[0] << 24) | ((uint32_t)body[1] << 16) | ((uint32_t)body[2] << 8) | body[3];
    if (sequence == UINT32_MAX || next != sequence + 1) return fail(req, "409 Conflict", "Sequence mismatch; inspect screen");
    if (body[5] < 4 || body[5] > 0x73) return fail(req, "400 Bad Request", "Invalid key");
    if (release_pending && !release_keys()) return fail(req, "503 Service Unavailable", "Release pending");
    if (!ready()) return fail(req, "503 Service Unavailable", "USB unavailable");
    // Consume sequence before submitting: never automatically replay an ambiguous keystroke.
    sequence = next;
    uint8_t keys[6] = {body[5]};
    release_pending = true;
    if (!tud_hid_keyboard_report(0, body[4], keys)) {
        armed_until = 0;
        return fail(req, "503 Service Unavailable", "USB submit failed; inspect screen");
    }
    vTaskDelay(pdMS_TO_TICKS(50));
    if (!release_keys()) {
        armed_until = 0;
        return fail(req, "503 Service Unavailable", "Release failed; inspect screen");
    }
    return httpd_resp_sendstr(req, "OK");
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED)) {
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        ESP_LOGI("network", "IP: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}
void app_main(void) {
    // Do not erase NVS on initialization error.
    ESP_ERROR_CHECK(nvs_flash_init());
    tinyusb_config_t usb = TINYUSB_DEFAULT_CONFIG();
    usb.descriptor.full_speed_config = config_desc;
    usb.descriptor.string = strings;
    usb.descriptor.string_count = 5;
    ESP_ERROR_CHECK(tinyusb_driver_install(&usb));
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t wifi = {.sta = {.ssid = WIFI_SSID, .password = WIFI_PASSWORD,
        .threshold.authmode = WIFI_AUTH_WPA2_PSK, .pmf_cfg = {.capable = true}}};
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    configASSERT(xTaskCreate(discovery, "discovery", 3072, NULL, 3, NULL) == pdPASS);
    extern const unsigned char cert_start[] asm("_binary_servercert_pem_start");
    extern const unsigned char cert_end[] asm("_binary_servercert_pem_end");
    extern const unsigned char key_start[] asm("_binary_prvtkey_pem_start");
    extern const unsigned char key_end[] asm("_binary_prvtkey_pem_end");
    httpd_ssl_config_t https = HTTPD_SSL_CONFIG_DEFAULT();
    https.httpd.max_open_sockets = 2;
    https.httpd.recv_wait_timeout = 3;
    https.httpd.send_wait_timeout = 3;
    https.servercert = cert_start;
    https.servercert_len = cert_end - cert_start;
    static esp_key_config_t key = {.source = ESP_KEY_SOURCE_BUFFER, .buffer.data = key_start};
    key.buffer.len = key_end - key_start;
    https.server_key = &key;
    httpd_handle_t server;
    ESP_ERROR_CHECK(httpd_ssl_start(&server, &https));
    const httpd_uri_t routes[] = {
        {.uri="/status", .method=HTTP_GET, .handler=api},
        {.uri="/arm", .method=HTTP_POST, .handler=api},
        {.uri="/disarm", .method=HTTP_POST, .handler=api},
        {.uri="/key", .method=HTTP_POST, .handler=api}
    };
    for (size_t i = 0; i < sizeof(routes)/sizeof(routes[0]); ++i) ESP_ERROR_CHECK(httpd_register_uri_handler(server, &routes[i]));
}
