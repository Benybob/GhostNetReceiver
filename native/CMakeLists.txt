cmake_minimum_required(VERSION 3.22)
project(GhostNetJS8 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core)
find_package(Boost 1.77 REQUIRED)
find_library(FFTW_SINGLE fftw3f REQUIRED)
add_library(ghostnet_js8 SHARED
  engine.cpp
  upstream/JS8_Mode/FrequencyTracker.cpp
  upstream/JS8_Mode/DecodedText.cpp
  upstream/JS8_Main/Varicode.cpp
  upstream/JS8_Main/Varicode.h
  upstream/JS8_JSC/JSC.cpp
  upstream/JS8_JSC/JSC_list.cpp
  upstream/JS8_JSC/JSC_map.cpp)
target_include_directories(ghostnet_js8 PRIVATE upstream upstream/JS8_Mode ${Boost_INCLUDE_DIRS})
target_link_libraries(ghostnet_js8 PRIVATE Qt6::Core ${FFTW_SINGLE})
target_compile_options(ghostnet_js8 PRIVATE -O2 -Wno-deprecated-declarations)
set_target_properties(ghostnet_js8 PROPERTIES PREFIX "" OUTPUT_NAME "ghostnet_js8")
