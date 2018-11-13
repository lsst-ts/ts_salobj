"""Sphinx configuration file for an LSST stack package.

This configuration only affects single-package Sphinx documenation builds.
"""

from documenteer.sphinxconfig.stackconf import build_package_configs
from lsst.ts.salobj import version


_g = globals()
_g.update(build_package_configs(
    project_name='ts_salobj',
    version=version.__version__))
