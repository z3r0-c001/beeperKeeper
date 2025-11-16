/*
 * ESP32 Water Level Monitor with MQTT - BeeperKeeper Integration
 * Board: ESP32 DevKit V1 (DOIT)
 * Sensor: HC-SR04 Ultrasonic
 *
 * Wiring:
 * HC-SR04 VCC  -> 5V Power Rail
 * HC-SR04 GND  -> GND Power Rail
 * HC-SR04 TRIG -> ESP32 GPIO 32
 * HC-SR04 ECHO -> ESP32 GPIO 33
 * ESP32 powered from same 5V rail (5V/3A supply)
 *
 * Required Libraries (Install via Library Manager):
 * - PubSubClient (MQTT client)
 * - ArduinoJson (JSON serialization)
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <esp_task_wdt.h>
#include <ArduinoOTA.h>

// WiFi Configuration
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// MQTT Configuration
const char* mqtt_server = "10.10.10.7";
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_WaterLevel";

// MQTT Topics - BeeperKeeper namespace
const char* topic_water_data = "beeper/water/tank";
const char* topic_status = "beeper/water/status";

// Sensor Configuration
#define TRIG_PIN 32
#define ECHO_PIN 33
#define SOUND_SPEED 0.034  // cm/us at ~20°C
#define TANK_HEIGHT 27.94  // 11 inches (279.4mm)

// Measurement Configuration
#define NUM_SAMPLES 5          // Number of measurements to average
#define MIN_VALID_DISTANCE 2.0 // HC-SR04 minimum range (cm)
#define MAX_VALID_DISTANCE 400.0 // HC-SR04 maximum range (cm)
#define MAX_CONSECUTIVE_ERRORS 10

// Timing Configuration
const long publishInterval = 30000;  // Publish every 30 seconds (reduced from 5s)
#define WDT_TIMEOUT 30  // Watchdog timeout in seconds

WiFiClient espClient;
PubSubClient client(espClient);

unsigned long lastMsg = 0;
const long statusPublishInterval = 300000;  // Status heartbeat every 5 minutes
unsigned long lastStatusMsg = 0;
int consecutiveErrors = 0;
unsigned long bootCount = 0;

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Enable watchdog timer (ESP32 Arduino Core 3.0+ API)
  esp_task_wdt_config_t wdt_config = {
    .timeout_ms = WDT_TIMEOUT * 1000,  // Convert seconds to milliseconds
    .idle_core_mask = 0,                // Watch all cores
    .trigger_panic = true               // Reboot on timeout
  };
  esp_task_wdt_init(&wdt_config);
  esp_task_wdt_add(NULL);

  delay(1000);
  Serial.println("\n\n=================================");
  Serial.println("ESP32 Water Level Monitor v2.0");
  Serial.println("BeeperKeeper Integration");
  Serial.println("=================================");
  Serial.println("Tank Height: " + String(TANK_HEIGHT) + " cm");
  Serial.println("Publish Interval: " + String(publishInterval / 1000) + " seconds");
  Serial.println("Samples per reading: " + String(NUM_SAMPLES));
  Serial.println("----------------------------");

  bootCount++;

  setupWiFi();
  client.setServer(mqtt_server, mqtt_port);

  // Setup OTA updates
  setupOTA();

  // Configure NTP for timestamp (using reliable NTP pool)
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.println("Waiting for NTP time sync (pool.ntp.org)...");

  // Wait for time sync (up to 30 seconds)
  int ntpRetries = 0;
  while (time(nullptr) < 100000 && ntpRetries < 60) {
    esp_task_wdt_reset();  // Feed watchdog during NTP sync
    delay(500);
    Serial.print(".");
    ntpRetries++;
  }
  Serial.println();

  if (time(nullptr) > 100000) {
    time_t now = time(nullptr);
    Serial.print("NTP time synchronized: ");
    Serial.println(ctime(&now));
  } else {
    Serial.println("WARNING: NTP time sync failed after 30 seconds");
    Serial.println("Check internet connectivity - using millis() for timestamps");
  }

  Serial.println("Setup complete. Starting measurements...\n");
}

void loop() {
  // Feed the watchdog
  esp_task_wdt_reset();

  // Handle OTA updates
  ArduinoOTA.handle();

  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected! Reconnecting...");
    setupWiFi();
    return;
  }

  // Check MQTT connection
  if (!client.connected()) {
    reconnectMQTT();
  }
  client.loop();

  unsigned long now = millis();
  if (now - lastMsg > publishInterval) {
    lastMsg = now;

    float distance = measureDistanceAverage();

    if (distance > 0) {
      // Valid reading received
      consecutiveErrors = 0;

      float waterLevel = TANK_HEIGHT - distance;
      float percentFull = (waterLevel / TANK_HEIGHT) * 100.0;

      // Ensure values are within bounds
      if (waterLevel < 0) waterLevel = 0;
      if (percentFull < 0) percentFull = 0;
      if (percentFull > 100) percentFull = 100;

      // Print to serial
      Serial.print("📏 Distance: ");
      Serial.print(distance, 1);
      Serial.print(" cm | 💧 Level: ");
      Serial.print(waterLevel, 1);
      Serial.print(" cm | 📊 Tank: ");
      Serial.print(percentFull, 1);
      Serial.print("% | 📶 WiFi: ");
      Serial.print(WiFi.RSSI());
      Serial.println(" dBm");

      // Publish to MQTT
      publishMQTT(distance, waterLevel, percentFull);

    } else {
      consecutiveErrors++;
      Serial.println("❌ Error: Invalid reading (" + String(consecutiveErrors) + "/" + String(MAX_CONSECUTIVE_ERRORS) + ")");

      if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        Serial.println("⚠️  SENSOR FAILURE: Too many consecutive errors!");
        publishError("sensor_failure");
      }
    }
  }

  // Periodic status heartbeat (every 5 minutes)
  if (now - lastStatusMsg > statusPublishInterval) {
    lastStatusMsg = now;
    publishStatusHeartbeat();
  }
}

void setupWiFi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 30) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("✓ WiFi connected");
    Serial.print("  IP address: ");
    Serial.println(WiFi.localIP());
    Serial.print("  Signal strength: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println();
    Serial.println("✗ WiFi connection failed!");
    Serial.println("  Continuing with retries...");
  }
}

void setupOTA() {
  // Hostname for OTA
  ArduinoOTA.setHostname("ESP32-WaterLevel");

  // Password for OTA (CHANGE THIS!)
  ArduinoOTA.setPassword("beeper2025");

  // Port for OTA (default 3232)
  ArduinoOTA.setPort(3232);

  ArduinoOTA.onStart([]() {
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH) {
      type = "sketch";
    } else {  // U_SPIFFS
      type = "filesystem";
    }
    Serial.println("OTA Update Start: " + type);
  });

  ArduinoOTA.onEnd([]() {
    Serial.println("\nOTA Update Complete!");
  });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("OTA Progress: %u%%\r", (progress / (total / 100)));
  });

  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("OTA Error[%u]: ", error);
    if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR) Serial.println("End Failed");
  });

  ArduinoOTA.begin();
  Serial.println("✓ OTA updates enabled");
  Serial.print("  Hostname: ESP32-WaterLevel");
  Serial.print(" | IP: ");
  Serial.println(WiFi.localIP());
}

void reconnectMQTT() {
  // Non-blocking reconnection with timeout
  static unsigned long lastReconnectAttempt = 0;
  unsigned long now = millis();

  if (now - lastReconnectAttempt > 5000) {
    lastReconnectAttempt = now;
    Serial.print("Attempting MQTT connection to ");
    Serial.print(mqtt_server);
    Serial.print(":");
    Serial.print(mqtt_port);
    Serial.print("...");

    // Attempt to connect (no authentication for BeeperKeeper broker)
    if (client.connect(mqtt_client_id)) {
      Serial.println(" ✓ connected");

      // Publish online status
      StaticJsonDocument<192> statusDoc;  // Increased buffer for additional fields
      statusDoc["status"] = "online";
      statusDoc["boot_count"] = bootCount;
      statusDoc["rssi"] = WiFi.RSSI();
      statusDoc["ip"] = WiFi.localIP().toString();
      statusDoc["timestamp"] = getUnixTime();
      statusDoc["sensor_type"] = "water_level";  // ADD - for tag consistency
      statusDoc["location"] = "coop_main";        // ADD - for tag consistency

      char buffer[192];  // Match buffer size
      serializeJson(statusDoc, buffer);
      client.publish(topic_status, buffer, true);  // retained=true

    } else {
      Serial.print(" ✗ failed, rc=");
      Serial.println(client.state());
    }
  }
}

void publishMQTT(float distance, float waterLevel, float percentFull) {
  StaticJsonDocument<384> doc;

  // Sensor readings
  doc["distance_cm"] = round(distance * 10) / 10.0;  // Round to 1 decimal
  doc["water_level_cm"] = round(waterLevel * 10) / 10.0;
  doc["percent_full"] = round(percentFull * 10) / 10.0;
  doc["tank_height_cm"] = TANK_HEIGHT;

  // Metadata for Telegraf tag extraction
  doc["sensor_type"] = "water_level";
  doc["location"] = "coop_main";

  // System info
  doc["rssi"] = WiFi.RSSI();
  doc["heap_free"] = ESP.getFreeHeap();
  doc["uptime_s"] = millis() / 1000;

  // Timestamp removed - let Telegraf use current server time
  // This ensures data appears with correct timestamps in InfluxDB

  char buffer[384];
  serializeJson(doc, buffer);

  if (client.publish(topic_water_data, buffer)) {
    Serial.println("✓ MQTT published");
  } else {
    Serial.println("✗ MQTT publish failed");
  }
}

void publishError(const char* errorType) {
  StaticJsonDocument<256> doc;

  doc["status"] = "error";
  doc["error_type"] = errorType;
  doc["consecutive_errors"] = consecutiveErrors;
  doc["sensor_type"] = "water_level";
  doc["location"] = "coop_main";
  // Timestamp removed - let Telegraf use current server time

  char buffer[256];
  serializeJson(doc, buffer);
  client.publish(topic_status, buffer);
}

void publishStatusHeartbeat() {
  StaticJsonDocument<192> statusDoc;
  statusDoc["status"] = "online";
  statusDoc["boot_count"] = bootCount;
  statusDoc["rssi"] = WiFi.RSSI();
  statusDoc["ip"] = WiFi.localIP().toString();
  statusDoc["timestamp"] = getUnixTime();
  statusDoc["sensor_type"] = "water_level";
  statusDoc["location"] = "coop_main";

  char buffer[192];
  serializeJson(statusDoc, buffer);

  if (client.publish(topic_status, buffer, true)) {
    Serial.println("📡 Status heartbeat published");
  }
}

float measureDistanceAverage() {
  float readings[NUM_SAMPLES];
  int validCount = 0;

  // Take multiple samples
  for (int i = 0; i < NUM_SAMPLES; i++) {
    float d = measureDistanceSingle();

    // Validate reading is within HC-SR04 range
    if (d >= MIN_VALID_DISTANCE && d <= MAX_VALID_DISTANCE) {
      readings[validCount++] = d;
    }

    if (i < NUM_SAMPLES - 1) {
      delay(50);  // Wait between samples to avoid interference
    }
  }

  // Need at least 3 valid readings
  if (validCount < 3) {
    return -1;
  }

  // Sort readings using bubble sort (simple for small arrays)
  for (int i = 0; i < validCount - 1; i++) {
    for (int j = 0; j < validCount - i - 1; j++) {
      if (readings[j] > readings[j + 1]) {
        float temp = readings[j];
        readings[j] = readings[j + 1];
        readings[j + 1] = temp;
      }
    }
  }

  // Return median value (most robust against outliers)
  return readings[validCount / 2];
}

float measureDistanceSingle() {
  // Clear trigger
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  // Send 10us pulse
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Read echo pulse (30ms timeout)
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);

  if (duration == 0) {
    return -1;  // No echo received (sensor error or out of range)
  }

  // Calculate distance in cm
  float distance = (duration * SOUND_SPEED) / 2.0;

  return distance;
}

unsigned long getUnixTime() {
  time_t now = time(nullptr);

  // If NTP time is valid (after year 2001), return it
  if (now > 1000000000) {
    return now;
  }

  // Fallback: use millis() as timestamp (relative time)
  return millis() / 1000;
}
