#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h> 
#include "esp_camera.h"
#include "esp_http_server.h"
#include <HTTPClient.h>
#include <Preferences.h>

// --- ESP32-CAM (AI-Thinker Pinout) ---
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM  4
#define SIOC_GPIO_NUM  5
#define Y2_GPIO_NUM    11
#define Y3_GPIO_NUM    9
#define Y4_GPIO_NUM    8
#define Y5_GPIO_NUM    10
#define Y6_GPIO_NUM    12
#define Y7_GPIO_NUM    18
#define Y8_GPIO_NUM    17
#define Y9_GPIO_NUM    16
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7
#define PCLK_GPIO_NUM  13

const int PIR_PIN = 2;
bool streaming_active = true;
unsigned long last_wake_time = 0;
const unsigned long TIMEOUT_MS = 3000; 

// Глобални променливи за съхранение на конфигурацията
char fastapi_url[100] = "192.168.68.53:8000"; 
char room_number[10] = "1151";

Preferences preferences;
httpd_handle_t camera_httpd = NULL;

// Сърцебиене и автоматичен повторен опит за регистрация
bool is_registered = false;
unsigned long last_register_attempt = 0;
const unsigned long REGISTER_RETRY_INTERVAL = 10000; // 10 сек опит при провал
const unsigned long HEARTBEAT_INTERVAL = 45000;      // 45 сек периодично поддържане

bool registerCameraToBackend(String target_url, String room, String ip);

// --- MJPEG STREAM CONFIGURATION ---
#define PART_BOUNDARY "frame"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace; boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// --- NON-BLOCKING STREAM HANDLER (esp_http_server) ---
static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char part_buf[128];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) {
    return res;
  }
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  Serial.println("[STREAM] Client connected (esp_http_server).");

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAMERA] Frame capture failed");
      res = ESP_FAIL;
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }

    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }
    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }

    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    }

    if (res != ESP_OK) {
      break;
    }

    // Оптимално забавяне (~25-30 FPS). Предотвратява препълване на TCP буфера при Wi-Fi латентност.
    vTaskDelay(pdMS_TO_TICKS(12));
  }

  Serial.println("[STREAM] Client disconnected (esp_http_server).");
  return res;
}

// --- STOP HANDLER ---
static esp_err_t stop_handler(httpd_req_t *req) {
  streaming_active = false;
  const char* resp = "Stream stopped.";
  httpd_resp_send(req, resp, strlen(resp));
  Serial.println("[COMMAND] Stop received.");
  return ESP_OK;
}

// --- CONFIG PAGE (GET) ---
static esp_err_t config_get_handler(httpd_req_t *req) {
  String html = "<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                "<style>body{font-family:Arial;background:#f4f6f7;padding:20px;text-align:center;}"
                ".form-card{background:white;max-width:400px;margin:0 auto;padding:20px;border-radius:10px;box-shadow:0 4px 6px rgba(0,0,0,0.1);text-align:left;}"
                "h2{text-align:center;color:#34495e;margin-bottom:20px;}"
                "label{font-weight:bold;color:#7f8c8d;display:block;margin-bottom:5px;}"
                "input[type=text]{width:100%;padding:10px;margin-bottom:20px;border:1px solid #bdc3c7;border-radius:5px;box-sizing:border-box;font-size:16px;}"
                "button{background:#2ecc71;color:white;width:100%;border:0;padding:12px;border-radius:5px;font-size:16px;font-weight:bold;cursor:pointer;}"
                "button:hover{background:#27ae60;}"
                ".info{font-size:13px;color:#95a5a6;margin-top:-15px;margin-bottom:15px;}</style></head><body>"
                "<div class='form-card'><h2>⚙️ Настройка на Терминал</h2>"
                "<form method='POST' action='/config'>"
                "<label>Номер на изпитна зала:</label>"
                "<input type='text' name='room' value='" + String(room_number) + "'>"
                "<p class='info'>Текуща: Зала " + String(room_number) + "</p>"
                "<label>FastAPI Сървър (ip:port):</label>"
                "<input type='text' name='api' value='" + String(fastapi_url) + "'>"
                "<p class='info'>Текущ: " + String(fastapi_url) + "</p>"
                "<button type='submit'>💾 Запази и Регистрирай</button>"
                "</form></div></body></html>";

  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html.c_str(), html.length());
}

// --- HELPER: URL DECODE ---
static void url_decode(char *dst, const char *src) {
  char a, b;
  while (*src) {
    if ((*src == '%') && ((a = src[1]) && (b = src[2])) && (isxdigit(a) && isxdigit(b))) {
      if (a >= 'a') a -= 'a' - 'A';
      if (a >= 'A') a -= ('A' - 10);
      else a -= '0';
      if (b >= 'a') b -= 'a' - 'A';
      if (b >= 'A') b -= ('A' - 10);
      else b -= '0';
      *dst++ = 16 * a + b;
      src += 3;
    } else if (*src == '+') {
      *dst++ = ' ';
      src++;
    } else {
      *dst++ = *src++;
    }
  }
  *dst++ = '\0';
}

// --- CONFIG PAGE (POST) ---
static esp_err_t config_post_handler(httpd_req_t *req) {
  char content[256];
  int remaining = req->content_len;

  if (remaining >= (int)sizeof(content)) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  int ret = httpd_req_recv(req, content, remaining);
  if (ret <= 0) {
    return ESP_FAIL;
  }
  content[ret] = '\0';

  char param[128];
  char decoded[128];

  if (httpd_query_key_value(content, "room", param, sizeof(param)) == ESP_OK) {
    url_decode(decoded, param);
    if (strlen(decoded) > 0) {
      strncpy(room_number, decoded, sizeof(room_number) - 1);
      room_number[sizeof(room_number) - 1] = '\0';
      preferences.begin("exam-gate", false);
      preferences.putString("room", String(room_number));
      preferences.end();
    }
  }

  if (httpd_query_key_value(content, "api", param, sizeof(param)) == ESP_OK) {
    url_decode(decoded, param);
    if (strlen(decoded) > 0) {
      strncpy(fastapi_url, decoded, sizeof(fastapi_url) - 1);
      fastapi_url[sizeof(fastapi_url) - 1] = '\0';
      preferences.begin("exam-gate", false);
      preferences.putString("api_url", String(fastapi_url));
      preferences.end();
    }
  }

  String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
  registerCameraToBackend(full_backend_path, String(room_number), WiFi.localIP().toString());

  String success_html = "<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                        "<style>body{font-family:Arial;text-align:center;padding-top:50px;background:#f4f6f7;}"
                        ".card{background:white;padding:30px;border-radius:10px;display:inline-block;box-shadow:0 4px 6px rgba(0,0,0,0.1);}"
                        "h2{color:#2ecc71;}</style></head><body><div class='card'>"
                        "<h2>✅ Настройките са запазени!</h2>"
                        "<p>Камерата е регистрирана за: <b>Зала " + String(room_number) + "</b></p>"
                        "<p>Адрес на сървъра: <b>" + String(fastapi_url) + "</b></p>"
                        "<p>Системата е в готовност (ARMED).</p>"
                        "<br><a href='/config'>Обратно към настройките</a>"
                        "</div></body></html>";

  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, success_html.c_str(), success_html.length());
}

// --- START ESP_HTTP_SERVER ---
void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 81;
  config.ctrl_port = 32768;
  config.max_open_sockets = 5;
  config.lru_purge_enable = true; // Затваря неактивни сокети автоматично

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t stop_uri = {
    .uri       = "/stop",
    .method    = HTTP_GET,
    .handler   = stop_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t config_get_uri = {
    .uri       = "/config",
    .method    = HTTP_GET,
    .handler   = config_get_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t config_post_uri = {
    .uri       = "/config",
    .method    = HTTP_POST,
    .handler   = config_post_handler,
    .user_ctx  = NULL
  };

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &stream_uri);
    httpd_register_uri_handler(camera_httpd, &stop_uri);
    httpd_register_uri_handler(camera_httpd, &config_get_uri);
    httpd_register_uri_handler(camera_httpd, &config_post_uri);
    Serial.println("[HTTPD] esp_http_server successfully started on port 81");
  } else {
    Serial.println("[HTTPD] ERROR: Failed to start esp_http_server!");
  }
}

// --- ROBUST FASTAPI REGISTRATION ---
bool registerCameraToBackend(String target_url, String room, String ip) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  HTTPClient http;
  http.begin(target_url); 
  http.addHeader("Content-Type", "application/json"); 
  http.setTimeout(8000); // 8-секунди таймаут за предотвратяване на фалшиви отпадания
  
  String jsonPayload = "{\"room_number\":\"" + room + "\", \"esp32_ip\":\"" + ip + "\"}";
  Serial.println("[REGISTER] Auto-registering to: " + target_url);
  
  int httpResponseCode = http.POST(jsonPayload);
  bool success = false;
  
  if (httpResponseCode > 0) {
    Serial.printf("[REGISTER] Registration SUCCESS (Code: %d)!\n", httpResponseCode);
    success = true;
    is_registered = true;
  } else {
    Serial.printf("[REGISTER] Error connecting to FastAPI: %d\n", httpResponseCode);
    is_registered = false;
  }
  
  http.end();
  last_register_attempt = millis();
  return success;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- [BOOT] Exam Gate Starting (Robust Server Edition) ---");

  pinMode(PIR_PIN, INPUT_PULLDOWN);

  preferences.begin("exam-gate", false);
  String saved_room = preferences.getString("room", "1151");
  saved_room.toCharArray(room_number, 10);
  String saved_url = preferences.getString("api_url", "192.168.68.53:8000");
  saved_url.toCharArray(fastapi_url, 100);
  preferences.end();

  // --- CAMERA INITIALIZATION ---
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0; 
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; 
  config.pin_d1 = Y3_GPIO_NUM; 
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM; 
  config.pin_d4 = Y6_GPIO_NUM; 
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; 
  config.pin_d7 = Y9_GPIO_NUM; 
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM; 
  config.pin_vsync = VSYNC_GPIO_NUM; 
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; 
  config.pin_sscb_scl = SIOC_GPIO_NUM; 
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM; 
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA; 
  config.jpeg_quality = 16; 
  config.fb_count = 2; 
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAMERA] Camera init failed with error 0x%x\n", err);
  } else {
    Serial.println("[CAMERA] Camera init OK!");
  }

  // --- WIFI MANAGER ---
  WiFiManager wm;
  wm.autoConnect("Exam-Gate-Config-WiFi");

  String current_ip = WiFi.localIP().toString();
  Serial.println("[WIFI] Connected!");
  Serial.print("[CONFIG] Web URL: http://"); Serial.print(current_ip); Serial.println(":81/config");

  // 1. СТАРТИРАМЕ ПЪРВО HTTPD СЪРВЪРА, ЗА ДА Е ГОТОВ ЗА СТРИЙМВАНЕ
  startCameraServer();

  // 2. СЛЕД ТОВА СЕ РЕГИСТРИРАМЕ ПРЕД FASTAPI
  String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
  registerCameraToBackend(full_backend_path, String(room_number), current_ip);

  Serial.println("[SYSTEM] System ARMED.");
}

void loop() {
  unsigned long now = millis();

  // Автоматичен повторен опит при неуспешна първоначална регистрация
  if (!is_registered) {
    if (now - last_register_attempt > REGISTER_RETRY_INTERVAL) {
      Serial.println("[RETRY] Retrying camera registration with FastAPI...");
      String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
      registerCameraToBackend(full_backend_path, String(room_number), WiFi.localIP().toString());
    }
  } else {
    // Периодично потвърждаване на регистрацията (Heartbeat)
    if (now - last_register_attempt > HEARTBEAT_INTERVAL) {
      String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
      registerCameraToBackend(full_backend_path, String(room_number), WiFi.localIP().toString());
    }
  }

  // PIR сензор логика
  if (!streaming_active) {
    if (digitalRead(PIR_PIN) == HIGH) {
      Serial.println("[PIR] Motion detected!");
      streaming_active = true;
      last_wake_time = now;
    }
  } else {
    if (now - last_wake_time > TIMEOUT_MS) {
      streaming_active = false;
    }
  }

  delay(10);
}