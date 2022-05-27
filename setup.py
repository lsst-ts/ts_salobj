import pathlib
from setuptools import setup
import setuptools_scm


setup(
    version=setuptools_scm.get_version(),
    scripts=[str(path) for path in pathlib.Path("bin").glob("*.py")],
)
