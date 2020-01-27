Object-oriented interface to `Service Abstraction Layer <https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527/>`_ (SAL) components.

`Documentation <https://ts-salobj.lsst.io>`_

The package is compatible with setuptools, as well as the Vera Rubin LSST DM's ``eups`` package management system and ``scons`` build system.
Assuming you have the basic DM stack installed you can do the following, from within the package directory:

* ``setup -r .`` to setup the package and dependencies, at which point the unit tests can be run and the package can be used "in place".
* ``pytest`` to run the unit tests.
* ``python setup.py install`` to install the software.
* ``package-docs build`` to build the documentation.
  This requires ``documenteer``; see `building single package docs`_ for installation instructions.

.. _building single package docs: https://developer.lsst.io/stack/building-single-package-docs.html
