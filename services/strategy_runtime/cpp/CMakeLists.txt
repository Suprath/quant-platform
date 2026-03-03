cmake_minimum_required(VERSION 3.16)
project(kira_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# High-performance build flags
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG -march=native -flto")

# Find pybind11 (installed via pip or system)
find_package(pybind11 REQUIRED)

# Build the Python extension module
pybind11_add_module(kira_engine
    bindings.cpp
)

target_include_directories(kira_engine PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Install to the same directory level as engine.py
install(TARGETS kira_engine DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/..)
