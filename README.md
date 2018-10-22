Object-oriented interface to [Service Abstraction Layer (SAL) components](https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527/).

Each component can be represented as an instance of `salobj.Controller` (to receive commands and output events and telemetry) or `salobj.Remote` (to issue commands to a remote SAL component and read events and telemetry from it).

The package is compatible with LSST DM's `scons` build system and `eups` package management system. Assuming you have the basic LSST DM stack installed you can do the following, from within the package directory:

- `setup -r .` to setup the package and dependencies.
- `scons` to build the package and run unit tests.
- `scons install declare` to install the package and declare it to eups.
- `package-docs build` to build the documentation.
  This requires optional [dependencies](https://developer.lsst.io/stack/building-single-package-docs.html) beyond those required to build and use the package.
