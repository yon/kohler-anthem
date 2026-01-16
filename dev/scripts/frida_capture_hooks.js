/*
 * Kohler Konnect - Traffic Capture Hooks (Development)
 *
 * This script contains ONLY the capture hooks - bypasses are loaded separately
 * from scripts/frida_bypass.js via the Python wrapper.
 *
 * Captures:
 * - HTTP/OkHttp requests
 * - IoT Hub connection strings
 * - MQTT messages
 * - Command payloads (Gson serialization)
 */

if (Java.available) {
    Java.perform(function() {
        console.log("\n" + "=".repeat(70));
        console.log("[*] Installing traffic capture hooks...");
        console.log("=".repeat(70) + "\n");

        // =====================================================================
        // HTTP/REST API CAPTURE
        // =====================================================================

        // OkHttp RealCall capture (captures all HTTP requests)
        try {
            var RealCall = Java.use("okhttp3.RealCall");

            RealCall.execute.implementation = function() {
                var request = this.request();
                var url = request.url().toString();
                var method = request.method();

                console.log("\n" + "=".repeat(70));
                console.log("[HTTP " + method + "] " + url);

                // Log headers (full, no truncation)
                var headers = request.headers();
                for (var i = 0; i < headers.size(); i++) {
                    var name = headers.name(i);
                    var value = headers.value(i);
                    if (name.toLowerCase() === "ocp-apim-subscription-key" ||
                        name.toLowerCase().indexOf("auth") !== -1) {
                        console.log("  " + name + ": " + value);
                    }
                }

                // Log body for non-GET requests
                if (method !== "GET") {
                    var body = request.body();
                    if (body != null) {
                        try {
                            var Buffer = Java.use("okio.Buffer");
                            var buffer = Buffer.$new();
                            body.writeTo(buffer);
                            var bodyStr = buffer.readUtf8();
                            console.log("  Body: " + bodyStr);
                        } catch(e) {}
                    }
                }
                console.log("=".repeat(70));

                return this.execute();
            };

            RealCall.enqueue.implementation = function(callback) {
                var request = this.request();
                var url = request.url().toString();
                var method = request.method();

                console.log("\n" + "=".repeat(70));
                console.log("[HTTP ASYNC " + method + "] " + url);

                if (method !== "GET") {
                    var body = request.body();
                    if (body != null) {
                        try {
                            var Buffer = Java.use("okio.Buffer");
                            var buffer = Buffer.$new();
                            body.writeTo(buffer);
                            var bodyStr = buffer.readUtf8();
                            console.log("  Body: " + bodyStr);
                        } catch(e) {}
                    }
                }
                console.log("=".repeat(70));

                return this.enqueue(callback);
            };
            console.log("[+] OkHttp RealCall capture installed");
        } catch(e) {
            console.log("[-] OkHttp capture failed: " + e);
        }

        // =====================================================================
        // IOT HUB / MQTT CAPTURE
        // =====================================================================

        // IoT Hub Connection String capture
        try {
            var IotHubConnectionString = Java.use("com.microsoft.azure.sdk.iot.device.IotHubConnectionString");
            IotHubConnectionString.$init.overload('java.lang.String').implementation = function(connectionString) {
                console.log("\n" + "*".repeat(70));
                console.log("[IOT HUB] CONNECTION STRING CAPTURED!");
                console.log("*".repeat(70));
                console.log(connectionString);
                console.log("*".repeat(70) + "\n");
                return this.$init(connectionString);
            };
            console.log("[+] IotHubConnectionString capture installed");
        } catch(e) {}

        // DeviceClient capture
        try {
            var DeviceClient = Java.use("com.microsoft.azure.sdk.iot.device.DeviceClient");
            DeviceClient.$init.overload('java.lang.String', 'com.microsoft.azure.sdk.iot.device.IotHubClientProtocol').implementation = function(connString, protocol) {
                console.log("\n[IOT HUB] DeviceClient created");
                console.log("  Protocol: " + protocol);
                console.log("  Connection: " + connString);
                return this.$init(connString, protocol);
            };
            console.log("[+] DeviceClient capture installed");
        } catch(e) {}

        // IoT Hub Message capture
        try {
            var Message = Java.use("com.microsoft.azure.sdk.iot.device.Message");
            Message.$init.overload('[B').implementation = function(bytes) {
                var str = Java.use("java.lang.String").$new(bytes);
                console.log("\n[IOT MESSAGE] " + str);
                return this.$init(bytes);
            };
            Message.$init.overload('java.lang.String').implementation = function(body) {
                console.log("\n[IOT MESSAGE] " + body);
                return this.$init(body);
            };
            console.log("[+] IoT Hub Message capture installed");
        } catch(e) {}

        // Paho MQTT Async Client capture
        try {
            var MqttAsyncClient = Java.use("org.eclipse.paho.client.mqttv3.MqttAsyncClient");

            MqttAsyncClient.connect.overload('org.eclipse.paho.client.mqttv3.MqttConnectOptions').implementation = function(options) {
                console.log("\n" + "*".repeat(70));
                console.log("[MQTT CONNECT] Server: " + this.getServerURI());
                console.log("[MQTT CONNECT] Client ID: " + this.getClientId());
                if (options) {
                    try {
                        console.log("[MQTT CONNECT] Username: " + options.getUserName());
                        var password = options.getPassword();
                        if (password) {
                            console.log("[MQTT CONNECT] Password: " + Java.use("java.lang.String").$new(password));
                        }
                        console.log("[MQTT CONNECT] Clean Session: " + options.isCleanSession());
                        console.log("[MQTT CONNECT] Keep Alive: " + options.getKeepAliveInterval());
                    } catch(e) {}
                }
                console.log("*".repeat(70) + "\n");
                return this.connect(options);
            };

            // Capture all publish overloads
            MqttAsyncClient.publish.overload('java.lang.String', 'org.eclipse.paho.client.mqttv3.MqttMessage').implementation = function(topic, message) {
                console.log("\n" + "-".repeat(70));
                console.log("[MQTT PUBLISH] Topic: " + topic);
                try {
                    var payload = message.getPayload();
                    var payloadStr = Java.use("java.lang.String").$new(payload);
                    console.log("[MQTT PUBLISH] QoS: " + message.getQos());
                    console.log("[MQTT PUBLISH] Retained: " + message.isRetained());
                    console.log("[MQTT PUBLISH] Payload: " + payloadStr);
                } catch(e) {
                    console.log("[MQTT PUBLISH] Payload: (binary, " + message.getPayload().length + " bytes)");
                }
                console.log("-".repeat(70));
                return this.publish(topic, message);
            };

            MqttAsyncClient.publish.overload('java.lang.String', '[B', 'int', 'boolean').implementation = function(topic, payload, qos, retained) {
                console.log("\n" + "-".repeat(70));
                console.log("[MQTT PUBLISH] Topic: " + topic);
                console.log("[MQTT PUBLISH] QoS: " + qos);
                console.log("[MQTT PUBLISH] Retained: " + retained);
                try {
                    var payloadStr = Java.use("java.lang.String").$new(payload);
                    console.log("[MQTT PUBLISH] Payload: " + payloadStr);
                } catch(e) {
                    console.log("[MQTT PUBLISH] Payload: (binary, " + payload.length + " bytes)");
                }
                console.log("-".repeat(70));
                return this.publish(topic, payload, qos, retained);
            };

            // Capture subscriptions
            MqttAsyncClient.subscribe.overload('java.lang.String', 'int').implementation = function(topic, qos) {
                console.log("\n[MQTT SUBSCRIBE] Topic: " + topic + " (QoS: " + qos + ")");
                return this.subscribe(topic, qos);
            };

            MqttAsyncClient.subscribe.overload('[Ljava.lang.String;', '[I').implementation = function(topics, qos) {
                console.log("\n[MQTT SUBSCRIBE] Multiple topics:");
                for (var i = 0; i < topics.length; i++) {
                    console.log("  - " + topics[i] + " (QoS: " + qos[i] + ")");
                }
                return this.subscribe(topics, qos);
            };

            console.log("[+] Paho MQTT AsyncClient capture installed");
        } catch(e) {
            console.log("[-] Paho MQTT AsyncClient capture failed: " + e);
        }

        // Paho MQTT Sync Client capture
        try {
            var MqttClient = Java.use("org.eclipse.paho.client.mqttv3.MqttClient");

            MqttClient.connect.overload('org.eclipse.paho.client.mqttv3.MqttConnectOptions').implementation = function(options) {
                console.log("\n" + "*".repeat(70));
                console.log("[MQTT SYNC CONNECT] Server: " + this.getServerURI());
                console.log("[MQTT SYNC CONNECT] Client ID: " + this.getClientId());
                if (options) {
                    try {
                        console.log("[MQTT SYNC CONNECT] Username: " + options.getUserName());
                        var password = options.getPassword();
                        if (password) {
                            console.log("[MQTT SYNC CONNECT] Password: " + Java.use("java.lang.String").$new(password));
                        }
                    } catch(e) {}
                }
                console.log("*".repeat(70) + "\n");
                return this.connect(options);
            };

            MqttClient.publish.overload('java.lang.String', 'org.eclipse.paho.client.mqttv3.MqttMessage').implementation = function(topic, message) {
                console.log("\n" + "-".repeat(70));
                console.log("[MQTT SYNC PUBLISH] Topic: " + topic);
                try {
                    var payload = message.getPayload();
                    var payloadStr = Java.use("java.lang.String").$new(payload);
                    console.log("[MQTT SYNC PUBLISH] Payload: " + payloadStr);
                } catch(e) {}
                console.log("-".repeat(70));
                return this.publish(topic, message);
            };

            MqttClient.subscribe.overload('java.lang.String').implementation = function(topic) {
                console.log("\n[MQTT SYNC SUBSCRIBE] Topic: " + topic);
                return this.subscribe(topic);
            };

            console.log("[+] Paho MQTT SyncClient capture installed");
        } catch(e) {}

        // MQTT Callback - capture received messages
        try {
            var MqttCallback = Java.use("org.eclipse.paho.client.mqttv3.MqttCallback");
            var MqttCallbackExtended = Java.use("org.eclipse.paho.client.mqttv3.MqttCallbackExtended");

            // Hook all implementations of messageArrived
            Java.enumerateLoadedClasses({
                onMatch: function(className) {
                    try {
                        var clazz = Java.use(className);
                        if (clazz.messageArrived) {
                            clazz.messageArrived.implementation = function(topic, message) {
                                console.log("\n" + "+".repeat(70));
                                console.log("[MQTT RECEIVED] Topic: " + topic);
                                try {
                                    var payload = message.getPayload();
                                    var payloadStr = Java.use("java.lang.String").$new(payload);
                                    console.log("[MQTT RECEIVED] QoS: " + message.getQos());
                                    console.log("[MQTT RECEIVED] Payload: " + payloadStr);
                                } catch(e) {
                                    console.log("[MQTT RECEIVED] Payload: (binary)");
                                }
                                console.log("+".repeat(70));
                                return this.messageArrived(topic, message);
                            };
                        }
                    } catch(e) {}
                },
                onComplete: function() {}
            });
            console.log("[+] MQTT Callback capture installed");
        } catch(e) {}

        // Azure IoT MQTT - capture device twin and direct methods
        try {
            var DeviceTwin = Java.use("com.microsoft.azure.sdk.iot.device.DeviceTwin.DeviceTwin");
            if (DeviceTwin) {
                console.log("[+] Azure IoT DeviceTwin class found");
            }
        } catch(e) {}

        // Capture raw MQTT wire protocol if available
        try {
            var MqttWireMessage = Java.use("org.eclipse.paho.client.mqttv3.internal.wire.MqttWireMessage");
            MqttWireMessage.getPayload.implementation = function() {
                var payload = this.getPayload();
                var msgType = this.getType();
                if (payload && payload.length > 0) {
                    try {
                        var payloadStr = Java.use("java.lang.String").$new(payload);
                        console.log("\n[MQTT WIRE] Type: " + msgType + " Payload: " + payloadStr);
                    } catch(e) {}
                }
                return payload;
            };
            console.log("[+] MQTT WireMessage capture installed");
        } catch(e) {}

        // =====================================================================
        // COMMAND/JSON CAPTURE
        // =====================================================================

        // Gson serialization capture (captures command objects)
        try {
            var Gson = Java.use("com.google.gson.Gson");
            Gson.toJson.overload('java.lang.Object').implementation = function(obj) {
                var json = this.toJson(obj);
                var className = obj.getClass().getName();

                // Filter for interesting classes
                var isInteresting =
                    className.indexOf("kohler") !== -1 ||
                    className.indexOf("hermoth") !== -1 ||
                    className.indexOf("Command") !== -1 ||
                    className.indexOf("Request") !== -1 ||
                    className.indexOf("Preset") !== -1 ||
                    className.indexOf("Warmup") !== -1 ||
                    className.indexOf("Valve") !== -1 ||
                    className.indexOf("Outlet") !== -1 ||
                    json.indexOf("deviceId") !== -1 ||
                    json.indexOf("presetId") !== -1 ||
                    json.indexOf("experienceId") !== -1 ||
                    json.indexOf("temperatureSetpoint") !== -1 ||
                    json.indexOf("flowSetpoint") !== -1;

                if (isInteresting && className.indexOf("microsoft") === -1) {
                    console.log("\n[GSON] " + className);
                    console.log(json);
                }
                return json;
            };
            console.log("[+] Gson command capture installed");
        } catch(e) {}

        // Retrofit request body capture
        try {
            var GsonRequestBodyConverter = Java.use("retrofit2.converter.gson.GsonRequestBodyConverter");
            GsonRequestBodyConverter.convert.overload('java.lang.Object').implementation = function(value) {
                var className = value.getClass().getName();
                console.log("\n[RETROFIT] " + className);
                try {
                    var Gson = Java.use("com.google.gson.Gson");
                    var gson = Gson.$new();
                    console.log(gson.toJson(value));
                } catch(e) {}
                return this.convert(value);
            };
            console.log("[+] Retrofit request body capture installed");
        } catch(e) {}

        // =====================================================================
        // IOT HUB SETTINGS CAPTURE (from HTTP response)
        // =====================================================================

        // IoTHubSettings - capture when connection string is set
        try {
            var IoTHubSettings = Java.use("com.utils.network.retrofit.proxy.platform.model.mobilesetting.iothubsettings.IoTHubSettings");

            IoTHubSettings.setConnectionString.implementation = function(str) {
                console.log("\n" + "*".repeat(70));
                console.log("[IOT HUB SETTINGS] CONNECTION STRING:");
                console.log(str);
                console.log("*".repeat(70));
                return this.setConnectionString(str);
            };

            IoTHubSettings.setDeviceId.implementation = function(str) {
                console.log("[IOT HUB SETTINGS] Device ID: " + str);
                return this.setDeviceId(str);
            };

            IoTHubSettings.setIoTHub.implementation = function(str) {
                console.log("[IOT HUB SETTINGS] IoT Hub: " + str);
                return this.setIoTHub(str);
            };

            IoTHubSettings.setUsername.implementation = function(str) {
                console.log("[IOT HUB SETTINGS] Username: " + str);
                return this.setUsername(str);
            };

            IoTHubSettings.setPassword.implementation = function(str) {
                console.log("[IOT HUB SETTINGS] Password: " + str);
                return this.setPassword(str);
            };

            IoTHubSettings.setClientId.implementation = function(str) {
                console.log("[IOT HUB SETTINGS] Client ID: " + str);
                return this.setClientId(str);
            };

            console.log("[+] IoTHubSettings capture installed");
        } catch(e) {
            console.log("[-] IoTHubSettings capture failed: " + e);
        }

        // MobileSettingResponse - capture full response
        try {
            var MobileSettingResponse = Java.use("com.utils.network.retrofit.proxy.platform.model.mobilesetting.MobileSettingResponse");

            MobileSettingResponse.setIoTHubSettings.implementation = function(settings) {
                console.log("\n" + "*".repeat(70));
                console.log("[MOBILE SETTING] IoT Hub Settings received!");
                if (settings != null) {
                    try {
                        var Gson = Java.use("com.google.gson.Gson");
                        var gson = Gson.$new();
                        console.log(gson.toJson(settings));
                    } catch(e) {
                        console.log("  (Could not serialize: " + e + ")");
                    }
                }
                console.log("*".repeat(70));
                return this.setIoTHubSettings(settings);
            };

            console.log("[+] MobileSettingResponse capture installed");
        } catch(e) {
            console.log("[-] MobileSettingResponse capture failed: " + e);
        }

        // =====================================================================
        // READY
        // =====================================================================

        console.log("\n" + "=".repeat(70));
        console.log("[*] ALL CAPTURE HOOKS INSTALLED");
        console.log("=".repeat(70));
        console.log("[*] Now sign in and control the shower");
        console.log("[*] Watch for:");
        console.log("    [HTTP]         - REST API requests");
        console.log("    [IOT HUB]      - IoT Hub connection strings");
        console.log("    [IOT MESSAGE]  - Messages to IoT Hub");
        console.log("    [MQTT CONNECT] - MQTT broker connections (server, user, pass)");
        console.log("    [MQTT PUBLISH] - Outgoing MQTT messages");
        console.log("    [MQTT SUBSCRIBE] - Topic subscriptions");
        console.log("    [MQTT RECEIVED] - Incoming MQTT messages");
        console.log("    [MQTT WIRE]    - Raw MQTT wire protocol");
        console.log("    [GSON]         - Command objects being serialized");
        console.log("    [RETROFIT]     - Request bodies");
        console.log("=".repeat(70) + "\n");
    });
}
