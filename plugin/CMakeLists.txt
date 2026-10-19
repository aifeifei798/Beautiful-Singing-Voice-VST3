cmake_minimum_required(VERSION 3.22)

project(BSVStudio VERSION 0.1.1 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# JUCE is not vendored into this repository (it is ~112 MB). Point JUCE_DIR at a
# checkout, or let the default find a sibling copy.
if(NOT DEFINED JUCE_DIR)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/JUCE/CMakeLists.txt")
        set(JUCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/JUCE")
    else()
        set(JUCE_DIR "$ENV{HOME}/develop/JUCE")
    endif()
endif()

if(NOT EXISTS "${JUCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "JUCE not found at ${JUCE_DIR}.\n"
        "Clone it with: git clone --depth 1 --branch 8.0.12 "
        "https://github.com/juce-framework/JUCE.git ${JUCE_DIR}\n"
        "then re-run cmake (or pass -DJUCE_DIR=...).")
endif()

add_subdirectory("${JUCE_DIR}" JUCE)

juce_add_plugin(BSVStudio
    PRODUCT_NAME            "Beautiful Singing Voice"
    COMPANY_NAME            "Feifei"
    BUNDLE_ID               "com.aifeifei.bsv"
    PLUGIN_MANUFACTURER_CODE Feif
    PLUGIN_CODE             Bsv1
    FORMATS                 VST3 Standalone
    IS_SYNTH                FALSE
    NEEDS_MIDI_INPUT        FALSE
    NEEDS_MIDI_OUTPUT       FALSE
    IS_MIDI_EFFECT          FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD TRUE
    VST3_CATEGORIES         "Fx"
    MICROPHONE_PERMISSION_ENABLED FALSE
)

target_sources(BSVStudio PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
)

target_include_directories(BSVStudio PRIVATE Source)

target_compile_definitions(BSVStudio PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0
    JUCE_REPORT_APP_USAGE=0
)

target_link_libraries(BSVStudio PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)

# Headless host used by scripts/verify_plugin.sh to check the VST3 without a DAW.
juce_add_console_app(BSVHost PRODUCT_NAME "bsv-host")
target_sources(BSVHost PRIVATE Tools/Host.cpp)
target_compile_definitions(BSVHost PRIVATE
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_STANDALONE_APPLICATION=1
    JUCE_PLUGINHOST_VST3=1
)
target_link_libraries(BSVHost PRIVATE
    juce::juce_audio_utils
    juce::juce_audio_processors
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)
