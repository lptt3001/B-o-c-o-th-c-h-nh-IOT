// Bai thuc hanh 2 - ESP32: DHT22 + HC-SR04 -> MQTT (JSON) -> broker cong cong
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHTesp.h>
#include <time.h>
#include <sys/time.h>

// ---------- Cau hinh ----------
const char* WIFI_SSID     = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";
const char* MQTT_SERVER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* DEVICE_ID     = "esp32-b23dccn856";
// Topic dang: iot/<ma_sv>/lab2/<vi_tri>/telemetry  (collector tach <vi_tri> lam tag "location")
const char* TOPIC         = "iot/b23dccn856/lab2/room1/telemetry";

const int DHT_PIN  = 15;
const int TRIG_PIN = 5;
const int ECHO_PIN = 18;
const int LED_PIN  = 2;
const unsigned long SEND_INTERVAL_MS = 5000;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHTesp dht;
unsigned long lastSend = 0;
unsigned long sequenceNo = 0;

// Thoi gian epoch (ms) sau khi dong bo NTP
int64_t nowMs() {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (int64_t)tv.tv_sec * 1000LL + tv.tv_usec / 1000;
}

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" connected");
}

void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  Serial.print("Syncing NTP");
  while (time(nullptr) < 1700000000) {
    delay(200);
    Serial.print(".");
  }
  Serial.println(" done");
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    String clientId = "ESP32-Lab2-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    Serial.print("Connecting MQTT...");
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println(" connected");
    } else {
      Serial.printf(" failed, rc=%d. Retry in 2 s\n", mqttClient.state());
      delay(2000);
    }
  }
}

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return NAN;
  return duration * 0.0343f / 2.0f;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  dht.setup(DHT_PIN, DHTesp::DHT22);
  connectWiFi();
  syncTime();
  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(512);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastSend < SEND_INTERVAL_MS) return;
  lastSend = now;

  TempAndHumidity data = dht.getTempAndHumidity();
  float distance = readDistanceCm();
  if (!isfinite(data.temperature) || !isfinite(data.humidity) || !isfinite(distance)) {
    Serial.println("Invalid sensor data - skip publish");
    return;
  }

  sequenceNo++;
  char payload[384];
  snprintf(payload, sizeof(payload),
           "{\"device_id\":\"%s\",\"ts\":%lld,\"temperature\":%.2f,\"humidity\":%.2f,"
           "\"distance_cm\":%.2f,\"rssi\":%d,\"seq\":%lu,\"uptime_s\":%lu}",
           DEVICE_ID, (long long)nowMs(), data.temperature, data.humidity, distance,
           WiFi.RSSI(), sequenceNo, millis() / 1000);

  bool ok = mqttClient.publish(TOPIC, payload);
  Serial.printf("%s | publish=%s\n", payload, ok ? "OK" : "FAILED");

  digitalWrite(LED_PIN, HIGH);
  delay(80);
  digitalWrite(LED_PIN, LOW);
}
