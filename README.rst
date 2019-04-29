Object-oriented interface to [Service Abstraction Layer (SAL) components](https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527/).

Each SAL component can be represented as an instance of:

* ``lsst.ts.salobj.Remote`` to issue commands to a remote SAL component and read events and telemetry from it.
* ``lsst.ts.salobj.ConfigurableCsc`` for a Commandable SAL Component (CSC) that is configured in the standard fashion.
* ``lsst.ts.salobj.BaseCsc`` for a CSC that does not need configuration.
* ``lsst.ts.salobj.Controller`` for a non-CSC to receive commands and output events and telemetry.

The package is compatible with LSST DM's ``scons`` build system and ``eups`` package management system.
Assuming you have the basic LSST DM stack installed you can do the following, from within the package directory:

* ``setup -r .`` to setup the package and dependencies.
* ``scons`` to build the package and run unit tests.
* ``scons install declare`` to install the package and declare it to eups.
* ``package-docs build`` to build the documentation.
  This requires ``documenteer``; see `building single package docs`_ for installation instructions.

.. _building single package docs: https://developer.lsst.io/stack/building-single-package-docs.html
