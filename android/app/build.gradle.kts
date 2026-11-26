import java.util.Properties

// Kotlin is compiled by AGP 9's built-in Kotlin support (no separate plugin).
plugins {
    id("com.android.application")
}

// Release signing only from the environment (CI secrets or a local
// keystore.properties that is never committed): no key lives in the repository.
val signingFile = rootProject.file("keystore.properties")
val signingProps = Properties().apply {
    if (signingFile.exists()) signingFile.inputStream().use { load(it) }
}
fun signing(name: String): String? = System.getenv("BSMD_$name") ?: signingProps.getProperty(name.lowercase())

android {
    namespace = "br.com.biglinux.bigscreen"
    compileSdk = 36

    defaultConfig {
        applicationId = "br.com.biglinux.bigscreen"
        minSdk = 21
        targetSdk = 36
        versionCode = 50600
        versionName = "5.6.0"
    }

    signingConfigs {
        val store = signing("KEYSTORE")
        if (store != null) {
            create("release") {
                storeFile = file(store)
                storePassword = signing("KEYSTORE_PASSWORD")
                keyAlias = signing("KEY_ALIAS")
                keyPassword = signing("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = true
        warningsAsErrors = false
        // Framework widgets on purpose (Android 5.0+ without AndroidX); see docs/android/06-aplicativo.md.
        disable += listOf("GradleDependency", "AndroidGradlePluginVersion", "OldTargetApi", "SetTextI18n")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
