from setuptools import setup, Extension
from pybind11.setup_helpers import Pybind11Extension, build_ext

ext_modules = [
    Pybind11Extension(
        "noise_filter_core",
        ["cpp/noise_filter_core.cpp"],
    ),
]

setup(
    name="noise_filter_core",
    version="1.0.0",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
