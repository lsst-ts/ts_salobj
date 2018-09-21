Object-oriented interface to [Service Abstraction Layer (SAL) components](https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527/).

Each component can be represented as an instance of `salobj.Controller` (to receive commands and output events and telemetry) or `salobj.Remote` (to issue commands to a remote  SAL component and read events and telemetry from it).

The package is compatible with LSST DM's build and package management system. Assuming you have the basic LSST DM stack installed you can do the following, from within the package directory:

- `scons` to build the package and run unit tests. Note that at present most of the unit tests rely on SAL libraries for component `Test` that are specific to unix that are included in the package. We hope to manage those libraries better in the future. On macOS most tests will be skipped.
- `setup -r .` to setup the package and dependencies
- `scons install` to install the package
- `package-docs build` to build the package. This requires optional [dependencies](https://developer.lsst.io/stack/building-single-package-docs.html) beyond those required to build and test the package.
