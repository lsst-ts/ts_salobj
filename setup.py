import setuptools
import setuptools_scm

setuptools.setup(
    version=setuptools_scm.get_version(
        write_to="python/lsst/ts/salobj/version.py", local_scheme="no-local-version"
    )
)
