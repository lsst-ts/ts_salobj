import os
import sys
import pathlib
import setuptools

install_requires = ["numpy", "astropy", "boto3", "moto", "ts-dds", "ts-idl>=1.2"]
tests_require = [
    "pytest",
    "pytest-cov",
    "pytest-flake8",
    "pytest-asyncio",
    "pytest-black",
    "ts-dds",
    "ts-idl>=1.2",
]
dev_requires = install_requires + tests_require + ["documenteer[pipelines]"]
scm_version_template = """# Generated by setuptools_scm
__all__ = ["__version__"]

__version__ = "{version}"
"""

tools_path = pathlib.Path(setuptools.__path__[0])
base_prefix = pathlib.Path(sys.base_prefix)
data_files_path = tools_path.relative_to(base_prefix).parents[1]


def local_scheme(version):
    return ""


setuptools.setup(
    name="ts_salobj",
    description="Object-oriented interface to LSST SAL communications middleware.",
    use_scm_version={
        "write_to": "python/lsst/ts/salobj/version.py",
        "write_to_template": scm_version_template,
        "local_scheme": local_scheme,
    },
    include_package_data=True,
    setup_requires=["setuptools_scm", "pytest-runner"],
    install_requires=install_requires,
    package_dir={"": "python"},
    packages=setuptools.find_namespace_packages(where="python"),
    package_data={"": ["*.rst", "*.yaml"]},
    data_files=[(os.path.join(data_files_path, "schema"), ["schema/Test.yaml"])],
    scripts=["bin/run_test_csc.py", "bin/zrun_test_commander.py"],
    tests_require=tests_require,
    extras_require={"dev": dev_requires},
    license="GPL",
    project_urls={
        "Bug Tracker": "https://jira.lsstcorp.org/secure/Dashboard.jspa",
        "Source Code": "https://github.com/lsst-ts/ts_salobj",
    },
)
