# 保留 kotlinx.serialization 生成的 serializer（反射不需要，但混淆后 R8 可能裁掉）
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class sujie.**$$serializer { *; }
-keepclassmembers class sujie.** { *** Companion; }
-keepclasseswithmembers class sujie.** { kotlinx.serialization.KSerializer serializer(...); }
