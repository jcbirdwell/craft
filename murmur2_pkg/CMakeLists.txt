cmake_minimum_required(VERSION 3.15)
project(${SKBUILD_PROJECT_NAME} LANGUAGES CXX)

find_package(pybind11 CONFIG REQUIRED)

# The name must match your Python import name
pybind11_add_module(_core
    ext/murmur2.cpp
)

# Install the module into the package directory
install(TARGETS _core DESTINATION murmur2)
