# ARES-ATAK plugin — ProGuard rules (skeleton).
# ATAK plugin classes are loaded reflectively by ATAK; keep the public surface.
-keep class com.ares.atak.plugin.** { *; }
-keepclassmembers class com.ares.atak.plugin.** { *; }

# transapps plugin framework entry points
-keep class * implements transapps.maps.plugin.lifecycle.Lifecycle { *; }
-keep class * implements transapps.maps.plugin.tool.Tool { *; }

# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-keep,includedescriptorclasses class com.ares.atak.plugin.net.**$$serializer { *; }
-keepclassmembers class com.ares.atak.plugin.net.** { *** Companion; }
-keepclasseswithmembers class com.ares.atak.plugin.net.** { kotlinx.serialization.KSerializer serializer(...); }

# Retrofit / OkHttp
-dontwarn okhttp3.**
-dontwarn retrofit2.**
-keepattributes Signature, Exceptions
