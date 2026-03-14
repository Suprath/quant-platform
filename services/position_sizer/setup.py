from setuptools import setup, Extension
from pybind11.setup_helpers import Pybind11Extension, build_ext

ext_modules = [
    Pybind11Extension(
        "position_sizer_core",
        ["cpp/position_sizer_core.cpp"],
    ),
]

setup(
    name="position_sizer_core",
    version="1.0.0",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
