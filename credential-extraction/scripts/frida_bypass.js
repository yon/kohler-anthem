/*
 * Kohler Konnect Bypass Script
 * Allows app to function on a rooted Android emulator (AVD).
 *
 * Required bypasses:
 * - License check (Pairip)
 * - Location injection (fake GPS + region code)
 * - SSL pinning (for mitmproxy)
 * - Root detection (Is.b class + File.* methods)
 * - Emulator detection (Build properties + SystemProperties)
 * - Proxy detection (hide proxy from app while allowing traffic through)
 */

if (Java.available) {
    Java.perform(function() {
        console.log("[*] Kohler Konnect bypass loaded");

        // NOTE: with the apktool-patched APK, the Konnect-side root check
        // (Is.b.n) returns false at the bytecode level, so we no longer need
        // Frida hooks to neutralize it. We DO still need:
        //   - LicenseClient bypass (Pairip — defense in depth alongside the
        //     installer-package=com.android.vending install flag)
        //   - SSL pinning bypass (mitmproxy interception)
        //   - KeyStore password capture (one-time recovery of the PKCS12 pw)
        //   - APIM key capture from SharedPreferences (legacy, still useful)
        //
        // The previous version of this script tried Java.deoptimizeEverything
        // + classloader switching + AlertDialog.show suppressors to make the
        // Is.b.n hook fire. None of that worked on Android 11 AVD (ART JIT
        // inlines the boolean helper methods even after deopt), AND the
        // combined hook overhead caused Konnect's SplashActivity → AzureLogin
        // transition to ANR. So we keep the script lean here.

        // =============== LICENSE CHECK BYPASS ===============
        try {
            var LicenseClient = Java.use("com.pairip.licensecheck.LicenseClient");
            LicenseClient.initializeLicenseCheck.implementation = function() {
                console.log("[*] LicenseClient.initializeLicenseCheck bypassed");
                var LicenseCheckState = Java.use("com.pairip.licensecheck.LicenseClient$LicenseCheckState");
                LicenseClient.licenseCheckState.value = LicenseCheckState.FULL_CHECK_OK.value;
            };
            LicenseClient.performLocalInstallerCheck.implementation = function() {
                return true;
            };
            console.log("[+] LicenseClient bypass installed");
        } catch(e) {
            console.log("[-] LicenseClient bypass failed: " + e);
        }

        // =============== LOCATION INJECTION ===============
        try {
            var BtDa = Java.use("Bt.d$a");
            var Location = Java.use("android.location.Location");
            var Handler = Java.use("android.os.Handler");
            var Looper = Java.use("android.os.Looper");
            var LocationPermissionActivity = Java.use("com.kohler.hermoth.products.feature.locationpermission.LocationPermissionActivity");

            BtDa.d.implementation = function(activity, callback) {
                console.log("[*] Bt.d.a.d() called - injecting fake location");
                var fakeLoc = Location.$new("gps");
                fakeLoc.setLatitude(43.7508);
                fakeLoc.setLongitude(-87.7819);
                fakeLoc.setAccuracy(10.0);
                fakeLoc.setTime(Java.use("java.lang.System").currentTimeMillis());
                fakeLoc.setElapsedRealtimeNanos(Java.use("android.os.SystemClock").elapsedRealtimeNanos());

                var mainHandler = Handler.$new(Looper.getMainLooper());
                var act = Java.cast(activity, LocationPermissionActivity);

                mainHandler.postDelayed(Java.registerClass({
                    name: "com.frida.FakeLocationInjector",
                    implements: [Java.use("java.lang.Runnable")],
                    methods: {
                        run: function() {
                            try {
                                act.D3(fakeLoc);
                                console.log("[*] Fake location injected successfully");
                            } catch(e) {
                                console.log("[-] Error calling D3: " + e);
                            }
                        }
                    }
                }).$new(), 500);
            };
            console.log("[+] Location injector installed");
        } catch(e) {
            console.log("[-] Location injector failed: " + e);
        }

        try {
            var BtDaA = Java.use("Bt.d$a$a");
            BtDaA.c.implementation = function() {
                console.log("[*] Region code bypassed - returning US");
                return "US";
            };
            console.log("[+] Region code bypass installed");
        } catch(e) {
            console.log("[-] Region code bypass failed: " + e);
        }

        // =============== SSL PINNING BYPASS ===============
        try {
            var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
            var SSLContext = Java.use('javax.net.ssl.SSLContext');

            var TrustManager = Java.registerClass({
                name: 'com.frida.BypassTrustManager',
                implements: [X509TrustManager],
                methods: {
                    checkClientTrusted: function(chain, authType) {},
                    checkServerTrusted: function(chain, authType) {},
                    getAcceptedIssuers: function() { return []; }
                }
            });

            var TrustManagers = [TrustManager.$new()];
            SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom').implementation = function(km, tm, sr) {
                console.log("[*] SSLContext.init bypassed");
                this.init(km, TrustManagers, sr);
            };
            console.log("[+] TrustManager bypass installed");
        } catch(e) {
            console.log("[-] TrustManager bypass failed: " + e);
        }

        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function(untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                console.log("[*] TrustManagerImpl.verifyChain bypassed for: " + host);
                return untrustedChain;
            };
            console.log("[+] TrustManagerImpl bypass installed");
        } catch(e) {
            console.log("[-] TrustManagerImpl bypass failed: " + e);
        }

        // =============== ROOTBEER NATIVE BYPASS ============================
        // Konnect ships RootBeer (confirmed via dex string scan). The Java
        // wrapper class has been renamed by ProGuard, but the native helper
        // `com.scottyab.rootbeer.RootBeerNative` keeps its name (JNI symbol
        // requirement). Neutralizing the native bridge handles the binary-
        // exists scan; the Java-side checks are handled by the dialog
        // suppressor below.
        try {
            var RootBeerNative = Java.use("com.scottyab.rootbeer.RootBeerNative");
            try {
                RootBeerNative.checkForRoot.overloads.forEach(function(ov) {
                    ov.implementation = function() { return 0; };
                });
            } catch (e) {}
            console.log("[+] RootBeerNative bypass installed");
        } catch (e) {
            console.log("[-] RootBeerNative bypass failed: " + e);
        }

        // (All the dialog/Activity.finish/Resources.getString/K3 hooks that
        // used to live here were removed 2026-05-10 after the apktool patch
        // proved sufficient. Hook overhead caused ANR on splash → login
        // transition. See konnect_runtime_bypass_notes.md for history.)

        // Is.b root-detection hooks are NO-OP now — the apktool patch
        // (scripts/apk_patch.py) makes Is.b.n() return false at the bytecode
        // level, which is what actually works. These hooks installed cleanly
        // but never fired because ART had JIT-inlined Is.b's boolean helpers.
        // Left as a no-op block in case a future Konnect build deobfuscates
        // and we want to re-enable.

        var rootPaths = [
            "/system/xbin/su", "/system/bin/su", "/sbin/su", "/su/bin/su",
            "/data/local/xbin/su", "/data/local/bin/su", "/data/local/su",
            "/system/sd/xbin/su", "/system/bin/failsafe/su",
            "/system/app/Superuser.apk", "/system/app/SuperSU.apk",
            "/system/app/SuperSU/SuperSU.apk",
            "/data/data/com.noshufou.android.su", "/data/data/eu.chainfire.supersu",
            "/data/data/com.koushikdutta.superuser", "/data/data/com.thirdparty.superuser",
            "/data/data/com.topjohnwu.magisk", "/cache/magisk.log",
            "/data/adb/magisk", "/sbin/.magisk",
            "/system/xbin/daemonsu", "/dev/com.koushikdutta.superuser.daemon",
            "/system/bin/.ext/su", "/system/usr/we-need-root/su",
            "/cache/su", "/data/su", "/dev/su",
            "/system/xbin/busybox", "/system/bin/busybox",
            "/product/bin/su", "/odm/bin/su", "/vendor/bin/su", "/vendor/xbin/su"
        ];

        function isRootPath(path) {
            for (var i = 0; i < rootPaths.length; i++) {
                if (path === rootPaths[i]) return true;
            }
            var p = path.toLowerCase();
            var rootPatterns = ["/magisk/", "/.magisk", "/supersu/", "/superuser/", "/xposed/", "/busybox"];
            for (var i = 0; i < rootPatterns.length; i++) {
                if (p.indexOf(rootPatterns[i]) !== -1) return true;
            }
            return false;
        }

        try {
            var File = Java.use("java.io.File");
            File.exists.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.exists.call(this);
            };
            File.canRead.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.canRead.call(this);
            };
            File.canWrite.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.canWrite.call(this);
            };
            File.canExecute.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.canExecute.call(this);
            };
            File.isFile.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.isFile.call(this);
            };
            File.isDirectory.implementation = function() {
                var path = this.getAbsolutePath();
                if (isRootPath(path)) return false;
                return this.isDirectory.call(this);
            };
            console.log("[+] File.* root path bypass installed");
        } catch(e) {
            console.log("[-] File.* bypass failed: " + e);
        }

        // =============== EMULATOR DETECTION BYPASS ===============
        try {
            var Build = Java.use("android.os.Build");
            Build.HARDWARE.value = "exynos2100";
            Build.PRODUCT.value = "o1sxxx";
            Build.MODEL.value = "SM-G991B";
            Build.MANUFACTURER.value = "samsung";
            Build.BRAND.value = "samsung";
            Build.DEVICE.value = "o1s";
            Build.BOARD.value = "exynos2100";
            Build.FINGERPRINT.value = "samsung/o1sxxx/o1s:13/TP1A.220624.014/G991BXXS7DWAA:user/release-keys";
            Build.TAGS.value = "release-keys";
            Build.TYPE.value = "user";
            console.log("[+] Build properties spoofed");
        } catch(e) {
            console.log("[-] Build spoof failed: " + e);
        }

        try {
            var SystemProperties = Java.use("android.os.SystemProperties");
            var originalGet = SystemProperties.get.overload('java.lang.String');
            SystemProperties.get.overload('java.lang.String').implementation = function(key) {
                var spoofProps = {
                    "ro.kernel.qemu": "0",
                    "ro.hardware": "exynos2100",
                    "ro.product.model": "SM-G991B",
                    "ro.build.tags": "release-keys",
                    "ro.debuggable": "0",
                    "ro.secure": "1"
                };
                if (spoofProps.hasOwnProperty(key)) return spoofProps[key];
                // Suppress known emulator-vendor strings so the app doesn't bail on detection.
                if (key.indexOf("vbox") !== -1 || key.indexOf("qemu") !== -1) return "";
                return originalGet.call(this, key);
            };
            SystemProperties.get.overload('java.lang.String', 'java.lang.String').implementation = function(key, def) {
                var result = SystemProperties.get.overload('java.lang.String').call(this, key);
                return result === "" ? def : result;
            };
            console.log("[+] SystemProperties bypass installed");
        } catch(e) {
            console.log("[-] SystemProperties bypass failed: " + e);
        }

        // TelephonyManager bypass (emulator detection via carrier info)
        try {
            var TelephonyManager = Java.use("android.telephony.TelephonyManager");
            TelephonyManager.getNetworkOperatorName.overload().implementation = function() { return "T-Mobile"; };
            TelephonyManager.getSimOperatorName.overload().implementation = function() { return "T-Mobile"; };
            TelephonyManager.getNetworkOperator.overload().implementation = function() { return "310260"; };
            TelephonyManager.getSimOperator.overload().implementation = function() { return "310260"; };
            TelephonyManager.getPhoneType.overload().implementation = function() { return 1; };
            console.log("[+] TelephonyManager emulator bypass installed");
        } catch(e) {
            console.log("[-] TelephonyManager bypass failed: " + e);
        }

        // =============== PROXY DETECTION BYPASS (DISABLED) ===============
        // Disabled 2026-05-10: these hooks hide the system proxy from the app
        // so well that the app's own networking code stops using it — which
        // defeats the whole point of routing through mitmproxy. The legacy
        // APIM-extraction flow assumed transparent-mode mitmproxy + iptables;
        // the /token-capture harness uses Android's system-proxy setting, so
        // the app MUST see http_proxy=10.0.2.2:8888 to actually route through.
        // If Konnect ever adds anti-MitM proxy detection that crashes the app,
        // re-enable these for the specific call sites only.
        console.log("[*] proxy-detection bypass intentionally disabled");

        // =============== APIM KEY CAPTURE ===============
        // Capture apim_key when stored in SharedPreferences
        try {
            var SharedPreferencesEditor = Java.use("android.content.SharedPreferences$Editor");
            var originalPutString = SharedPreferencesEditor.putString;
            SharedPreferencesEditor.putString.implementation = function(key, value) {
                if (key === "apim_key" && value && value.length > 0) {
                    console.log("");
                    console.log("============================================================");
                    console.log("CAPTURED APIM SUBSCRIPTION KEY!");
                    console.log("============================================================");
                    console.log("Key: " + value);
                    console.log("Stored in SharedPreferences as: " + key);
                    console.log("============================================================");
                    console.log("");
                }
                return originalPutString.call(this, key, value);
            };
            console.log("[+] SharedPreferences APIM key capture installed");
        } catch(e) {
            console.log("[-] SharedPreferences capture failed: " + e);
        }

        // Also hook the pt.a class method e() for SecurePreferences
        function installSecurePrefsHook() {
            try {
                var SecurePrefs = Java.use("pt.a");
                var originalE = SecurePrefs.e;
                SecurePrefs.e.implementation = function(key, value) {
                    if (key === "apim_key" && value && value.length > 0) {
                        console.log("");
                        console.log("============================================================");
                        console.log("CAPTURED APIM SUBSCRIPTION KEY (SecurePrefs)!");
                        console.log("============================================================");
                        console.log("Key: " + value);
                        console.log("============================================================");
                        console.log("");
                    }
                    return originalE.call(this, key, value);
                };
                console.log("[+] SecurePreferences APIM key capture installed");
                return true;
            } catch(e) {
                return false;
            }
        }

        // Try immediately, then schedule retries for SecurePrefs
        if (!installSecurePrefsHook()) {
            var hookInterval = setInterval(function() {
                Java.perform(function() {
                    if (installSecurePrefsHook()) {
                        clearInterval(hookInterval);
                    }
                });
            }, 1000);
            console.log("[*] SecurePreferences hook scheduled (waiting for class to load)");
        }

        // =============== KEYSTORE PASSWORD CAPTURE =========================
        // Konnect uses res/raw/auth_certificate.pfx as a client cert for
        // mTLS to the APIM gateway. The PFX password is the missing piece
        // for the auth-rewrite. Hook KeyStore.load and KeyManagerFactory.init
        // — both receive char[] passwords — and dump them when called.
        function dumpCharArray(label, chars) {
            if (!chars) return;
            try {
                var s = Java.use("java.lang.String").$new(chars);
                if (s && s.length() > 0) {
                    console.log("");
                    console.log("================================================================");
                    console.log("CAPTURED CRED [" + label + "]: " + s);
                    console.log("================================================================");
                    console.log("");
                }
            } catch (e) {
                console.log("[-] dumpCharArray failed: " + e);
            }
        }

        try {
            var KeyStore = Java.use("java.security.KeyStore");
            KeyStore.load.overload('java.io.InputStream', '[C').implementation = function(stream, password) {
                dumpCharArray("KeyStore.load", password);
                return this.load(stream, password);
            };
            console.log("[+] KeyStore.load(InputStream,char[]) hook installed");
        } catch (e) {
            console.log("[-] KeyStore.load hook failed: " + e);
        }

        try {
            var KMF = Java.use("javax.net.ssl.KeyManagerFactory");
            KMF.init.overload('java.security.KeyStore', '[C').implementation = function(ks, password) {
                dumpCharArray("KeyManagerFactory.init", password);
                return this.init(ks, password);
            };
            console.log("[+] KeyManagerFactory.init hook installed");
        } catch (e) {
            console.log("[-] KeyManagerFactory.init hook failed: " + e);
        }

        // OkHttp client-cert builder — Konnect uses OkHttp, so if it's
        // configuring client certs via the new heldCertificate API, catch
        // that too.
        try {
            var HandshakeCertificates = Java.use("okhttp3.tls.HandshakeCertificates");
            console.log("[+] HandshakeCertificates class found");
        } catch (e) { /* not bundled */ }

        // Also catch raw PKCS12 loads via PKCS12KeyStore directly
        try {
            var PKCS12 = Java.use("sun.security.pkcs12.PKCS12KeyStore");
            PKCS12.engineLoad.overload('java.io.InputStream', '[C').implementation = function(stream, password) {
                dumpCharArray("PKCS12KeyStore.engineLoad", password);
                return this.engineLoad(stream, password);
            };
            console.log("[+] PKCS12KeyStore.engineLoad hook installed");
        } catch (e) { /* not directly accessible — fine */ }

        // =============== INTENT TRACER ====================================
        // Log every startActivity call so we can see what Konnect launches
        // when the user taps Sign In (Chrome Custom Tab? WebView activity?
        // implicit intent to a browser?). Lightweight enough to leave on.
        try {
            var Activity = Java.use("android.app.Activity");
            Activity.startActivity.overload('android.content.Intent').implementation = function(intent) {
                console.log("[->] startActivity: " + intent.toString());
                return this.startActivity(intent);
            };
            Activity.startActivityForResult.overload('android.content.Intent', 'int').implementation = function(intent, code) {
                console.log("[->] startActivityForResult(" + code + "): " + intent.toString());
                return this.startActivityForResult(intent, code);
            };
            console.log("[+] startActivity tracer installed");
        } catch (eAct) {
            console.log("[-] startActivity tracer failed: " + eAct);
        }

        // CustomTabsIntent is OkHttp/AndroidX's wrapper around launching a
        // Chrome Custom Tab. If Konnect uses CCT for sign-in, we want to see
        // the URL.
        try {
            var CustomTabsIntent = Java.use("androidx.browser.customtabs.CustomTabsIntent");
            CustomTabsIntent.launchUrl.overload('android.content.Context', 'android.net.Uri').implementation = function(ctx, uri) {
                console.log("[->] CustomTabsIntent.launchUrl: " + uri.toString());
                return this.launchUrl(ctx, uri);
            };
            console.log("[+] CustomTabsIntent.launchUrl tracer installed");
        } catch (eCT) { /* not present */ }

        console.log("[*] All bypasses loaded");
    });
}
