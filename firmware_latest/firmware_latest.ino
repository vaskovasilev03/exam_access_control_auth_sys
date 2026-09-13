#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h> 
#include "esp_camera.h"
#include "esp_http_server.h"
#include <HTTPClient.h>
#include <Preferences.h>
#include "esp_wifi.h"

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
char camera_res[10] = "VGA";

Preferences preferences;
httpd_handle_t stream_httpd = NULL;
httpd_handle_t config_httpd = NULL;

// Сърцебиене и автоматичен повторен опит за регистрация
bool is_registered = false;
volatile int active_stream_clients = 0;
unsigned long last_register_attempt = 0;
const unsigned long REGISTER_RETRY_INTERVAL = 5000;   // 5 сек бърз повторен опит при неуспешна регистрация
const unsigned long HEARTBEAT_INTERVAL = 30000;       // 30 сек keep-alive когато няма активен клиент

bool registerCameraToBackend(String target_url, String room, String ip);

// --- MJPEG STREAM CONFIGURATION ---
#define PART_BOUNDARY "frame"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace; boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static unsigned long stream_fps_frames = 0;
static unsigned long stream_fps_last_calc = 0;
static float stream_live_fps = 0.0;

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

  active_stream_clients++;
  is_registered = true; // Бекендът чете кадри и знае, че сме активни
  Serial.printf("[STREAM] Client connected (esp_http_server). Active clients: %d\n", active_stream_clients);

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
    } else if (_jpg_buf) {
      free(_jpg_buf);
      _jpg_buf = NULL;
    }

    if (res != ESP_OK) {
      break;
    }

    // Изчисляване на живи кадри в секунда (Live FPS)
    stream_fps_frames++;
    unsigned long now_ms = millis();
    if (now_ms - stream_fps_last_calc >= 2000) {
      stream_live_fps = (stream_fps_frames * 1000.0f) / (now_ms - stream_fps_last_calc);
      stream_fps_frames = 0;
      stream_fps_last_calc = now_ms;
    }

    // 8ms пауза - дава процесорно време на Wi-Fi LwIP стека за гладък трансфер без блокиране (~25+ FPS)
    vTaskDelay(pdMS_TO_TICKS(8));
  }

  if (active_stream_clients > 0) {
    active_stream_clients--;
  }
  Serial.printf("[STREAM] Client disconnected (esp_http_server). Remaining clients: %d\n", active_stream_clients);
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
                "input[type=text], select{width:100%;padding:10px;margin-bottom:20px;border:1px solid #bdc3c7;border-radius:5px;box-sizing:border-box;font-size:16px;}"
                "button{background:#2ecc71;color:white;width:100%;border:0;padding:12px;border-radius:5px;font-size:16px;font-weight:bold;cursor:pointer;}"
                "button:hover{background:#27ae60;}"
                ".info{font-size:13px;color:#95a5a6;margin-top:-15px;margin-bottom:15px;}"
                ".badge{display:inline-block;padding:4px 8px;border-radius:4px;background:#e8f8f5;color:#27ae60;font-weight:bold;font-size:13px;margin-bottom:15px;}</style></head><body>"
                "<div class='form-card'><h2>Настройка на Терминал</h2>"
                "<div class='badge'>Видео поток: " + String(stream_live_fps, 1) + " FPS | Клиенти: " + String(active_stream_clients) + "</div>"
                "<form method='POST' action='/config'>"
                "<label>Номер на изпитна зала:</label>"
                "<input type='text' name='room' value='" + String(room_number) + "'>"
                "<p class='info'>Текуща: Зала " + String(room_number) + "</p>"
                "<label>FastAPI Сървър (ip:port):</label>"
                "<input type='text' name='api' value='" + String(fastapi_url) + "'>"
                "<p class='info'>Текущ: " + String(fastapi_url) + "</p>"
                "<label>Резолюция на камерата (FPS):</label>"
                "<select name='res'>"
                "<option value='VGA'" + String(strcmp(camera_res, "VGA") == 0 ? " selected" : "") + ">VGA (640x480) - Стандартна</option>"
                "<option value='HVGA'" + String(strcmp(camera_res, "HVGA") == 0 ? " selected" : "") + ">HVGA (480x320) - Висока скорост (25+ FPS)</option>"
                "<option value='QVGA'" + String(strcmp(camera_res, "QVGA") == 0 ? " selected" : "") + ">QVGA (320x240) - Максимална скорост</option>"
                "</select>"
                "<button type='submit'>Запази и Приложи</button>"
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

  if (httpd_query_key_value(content, "res", param, sizeof(param)) == ESP_OK) {
    url_decode(decoded, param);
    if (strlen(decoded) > 0) {
      strncpy(camera_res, decoded, sizeof(camera_res) - 1);
      camera_res[sizeof(camera_res) - 1] = '\0';
      preferences.begin("exam-gate", false);
      preferences.putString("res", String(camera_res));
      preferences.end();
      sensor_t *s = esp_camera_sensor_get();
      if (s != NULL) {
        if (strcmp(camera_res, "HVGA") == 0) {
          s->set_framesize(s, FRAMESIZE_HVGA);
        } else if (strcmp(camera_res, "QVGA") == 0) {
          s->set_framesize(s, FRAMESIZE_QVGA);
        } else {
          s->set_framesize(s, FRAMESIZE_VGA);
        }
      }
    }
  }

  String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
  registerCameraToBackend(full_backend_path, String(room_number), WiFi.localIP().toString());

  String success_html = "<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                        "<style>body{font-family:Arial;text-align:center;padding-top:50px;background:#f4f6f7;}"
                        ".card{background:white;padding:30px;border-radius:10px;display:inline-block;box-shadow:0 4px 6px rgba(0,0,0,0.1);}"
                        "h2{color:#2ecc71;}</style></head><body><div class='card'>"
                        "<h2>Настройките са запазени!</h2>"
                        "<p>Камерата е регистрирана за: <b>Зала " + String(room_number) + "</b></p>"
                        "<p>Адрес на сървъра: <b>" + String(fastapi_url) + "</b></p>"
                        "<p>Системата е в готовност (ARMED).</p>"
                        "<br><a href='/config'>Обратно към настройките</a>"
                        "</div></body></html>";

  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, success_html.c_str(), success_html.length());
}

// --- START DUAL HTTP SERVERS (PORT 80 FOR WEB UI, PORT 81 FOR STREAM) ---
void startCameraServer() {
  // 1. УЕБ СЪРВЪР ЗА НАСТРОЙКИ (ПОРТ 80)
  // Напълно независим FreeRTOS таск - винаги отговаря мигновено, дори когато стриймът върви на пълен FPS!
  httpd_config_t config_web = HTTPD_DEFAULT_CONFIG();
  config_web.server_port = 80;
  config_web.ctrl_port = 32767;
  config_web.max_open_sockets = 4;
  config_web.lru_purge_enable = true;

  // 2. СТРИЙМИНГ СЪРВЪР (ПОРТ 81)
  // Изолиран FreeRTOS таск единствено за високоефективния MJPEG видео поток
  httpd_config_t config_stream = HTTPD_DEFAULT_CONFIG();
  config_stream.server_port = 81;
  config_stream.ctrl_port = 32768;
  config_stream.max_open_sockets = 5;
  config_stream.stack_size = 8192;
  config_stream.lru_purge_enable = true;

  httpd_uri_t root_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = config_get_handler,
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

  httpd_uri_t stop_uri = {
    .uri       = "/stop",
    .method    = HTTP_GET,
    .handler   = stop_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  // Стартиране на Порт 80 (Web UI)
  if (httpd_start(&config_httpd, &config_web) == ESP_OK) {
    httpd_register_uri_handler(config_httpd, &root_uri);
    httpd_register_uri_handler(config_httpd, &config_get_uri);
    httpd_register_uri_handler(config_httpd, &config_post_uri);
    httpd_register_uri_handler(config_httpd, &stop_uri);
    Serial.println("[HTTPD] Web Config Server started on Port 80 (http://<ip>/config)");
  } else {
    Serial.println("[HTTPD] ERROR: Failed to start Web Config Server on Port 80!");
  }

  // Стартиране на Порт 81 (Stream + резервен /config)
  if (httpd_start(&stream_httpd, &config_stream) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
    httpd_register_uri_handler(stream_httpd, &config_get_uri);
    httpd_register_uri_handler(stream_httpd, &config_post_uri);
    httpd_register_uri_handler(stream_httpd, &stop_uri);
    Serial.println("[HTTPD] Video Stream Server started on Port 81 (http://<ip>:81/stream)");
  } else {
    Serial.println("[HTTPD] ERROR: Failed to start Stream Server on Port 81!");
  }
}

// --- ROBUST FASTAPI REGISTRATION ---
bool registerCameraToBackend(String target_url, String room, String ip) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[REGISTER] WiFi not connected, skipping registration.");
    return false;
  }

  // 1. Почистваме адреса от грешно въведени префикси, наклонени черти и интервали
  String clean_url = target_url;
  clean_url.trim();
  if (clean_url.startsWith("http://")) {
    clean_url = clean_url.substring(7);
  } else if (clean_url.startsWith("https://")) {
    clean_url = clean_url.substring(8);
  }
  while (clean_url.endsWith("/")) {
    clean_url = clean_url.substring(0, clean_url.length() - 1);
  }

  String host_port = clean_url;
  String path = "/api/v1/exams/register-camera";
  int slash_pos = clean_url.indexOf('/');
  if (slash_pos != -1) {
    host_port = clean_url.substring(0, slash_pos);
    path = clean_url.substring(slash_pos);
  }

  String final_url = "http://" + host_port + path;

  // Използваме експлицитен WiFiClient за максимална стабилност и чисто затваряне на сокетите
  WiFiClient client;
  client.setTimeout(2500);

  HTTPClient http;
  if (!http.begin(client, final_url)) {
    Serial.println("[REGISTER] http.begin() failed!");
    return false;
  }

  http.addHeader("Content-Type", "application/json"); 
  http.setTimeout(2500); // 2.5 сек таймаут за бърз отговор без блокиране на стрийма
  
  String jsonPayload = "{\"room_number\":\"" + room + "\", \"esp32_ip\":\"" + ip + "\"}";
  Serial.println("[REGISTER] Auto-registering to: " + final_url);
  
  int httpResponseCode = http.POST(jsonPayload);
  bool success = false;
  
  if (httpResponseCode == 200 || httpResponseCode == 201) {
    Serial.printf("[REGISTER] Registration SUCCESS (Code: %d)!\n", httpResponseCode);
    success = true;
    is_registered = true;
  } else {
    Serial.printf("[REGISTER] Error connecting to FastAPI: %d\n", httpResponseCode);
    if (active_stream_clients > 0) {
      is_registered = true; // Бекендът вече чете кадри от нас
    } else {
      is_registered = false;
    }
  }
  
  http.end();
  client.stop();
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
  String saved_res = preferences.getString("res", "VGA");
  saved_res.toCharArray(camera_res, 10);
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
  
  if (strcmp(camera_res, "HVGA") == 0) {
    config.frame_size = FRAMESIZE_HVGA;
  } else if (strcmp(camera_res, "QVGA") == 0) {
    config.frame_size = FRAMESIZE_QVGA;
  } else {
    config.frame_size = FRAMESIZE_VGA;
  }
  config.jpeg_quality = 16; 

  if (psramFound()) {
    config.fb_count = 2; 
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST; // Предотвратява натрупване на лаг, винаги предава най-новия кадър
    Serial.println("[CAMERA] PSRAM detected, using dual frame buffers with CAMERA_GRAB_LATEST.");
  } else {
    config.fb_count = 1; 
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
    Serial.println("[CAMERA] Warning: PSRAM not detected, fallback to single buffer.");
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAMERA] Camera init failed with error 0x%x\n", err);
  } else {
    Serial.println("[CAMERA] Camera init OK!");
    sensor_t *s = esp_camera_sensor_get();
    if (s != NULL) {
      // 8X gain ceiling позволява на сензора да поддържа висока скорост на затвора (1/30s - 1/50s) при стайно осветление
      s->set_gainceiling(s, GAINCEILING_8X);
      s->set_exposure_ctrl(s, 1); // Автоматична експозиция
      s->set_gain_ctrl(s, 1);     // Автоматично усилване
      s->set_brightness(s, 1);    // Лек софтуерен баланс
    }
  }

  // --- WIFI MANAGER ---
  WiFiManager wm;
  wm.autoConnect("Exam-Gate-Config-WiFi");

  // КРИТИЧНО ЗА ВИДЕО СТРИЙМ: ИЗКЛЮЧВАМЕ WI-FI POWER-SAVE РЕЖИМА!
  // Без това ESP32 заспива радио модула, пингът скача на 2000ms и има 20% загуба на пакети.
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);

  // Изчакваме кратък толеранс за установяване на рутирането и ARP таблицата
  delay(500);

  String current_ip = WiFi.localIP().toString();
  Serial.println("[WIFI] Connected!");
  Serial.print("[CONFIG] Web URL: http://"); Serial.print(current_ip); Serial.println("/config");
  Serial.print("[STREAM] Stream URL: http://"); Serial.print(current_ip); Serial.println(":81/stream");

  // 1. СТАРТИРАМЕ ПЪРВО HTTPD СЪРВЪРИТЕ (ПОРТ 80 И ПОРТ 81)
  startCameraServer();

  // 2. СЛЕД ТОВА СЕ РЕГИСТРИРАМЕ ПРЕД FASTAPI С ДО 3 ОПИТА
  String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
  for (int attempt = 1; attempt <= 3; attempt++) {
    Serial.printf("[BOOT-REGISTER] Registration attempt %d of 3...\n", attempt);
    if (registerCameraToBackend(full_backend_path, String(room_number), current_ip)) {
      break;
    }
    delay(1000);
  }

  Serial.println("[SYSTEM] System ARMED.");
}

void loop() {
  unsigned long now = millis();

  // Опитваме регистрация само ако камерата не е регистрирана и няма активен стрийм клиент.
  // Когато стриймът върви (active_stream_clients > 0), не правим HTTP заявки, за да няма лаг във видеото.
  if (!is_registered && active_stream_clients == 0) {
    if (now - last_register_attempt > REGISTER_RETRY_INTERVAL) {
      Serial.println("[RETRY] Retrying camera registration with FastAPI...");
      String full_backend_path = "http://" + String(fastapi_url) + "/api/v1/exams/register-camera";
      registerCameraToBackend(full_backend_path, String(room_number), WiFi.localIP().toString());
    }
  } else if (is_registered && active_stream_clients == 0) {
    // Периодичен Heartbeat на всеки 30 сек само ако никой не е свързан към стрийма
    // (напр. ако бекендът е бил рестартиран)
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