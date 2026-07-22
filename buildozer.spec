[app]

title = AliAnaliz
package.name = alianaliz
package.domain = org.alianaliz

source.dir = .
source.include_exts = py,kv,csv,png,jpg,ttf,atlas

version = 1.0.0

requirements = python3,kivy==2.3.1,requests,certifi,urllib3,chardet,idna,pyjnius

p4a.branch = master

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.minapi = 24
android.api = 34
android.ndk = 25b
android.sdk = 34
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
