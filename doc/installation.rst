############
Installation
############

ts_salobj is offered as a conda package.
The package is located on the `lsstts channel <https://anaconda.org/lsstts>`_.
ts_salobj requires opensplice in order to work correctly.
You can install opensplice using an RPM package located on the LSST Nexus repo.
This repository is only supported on CentOS 7.
You'll need to add a configuration file to have yum locate the repository.
Touch the following file ``/etc/yum.repos.d/lsst-ts.repo`` and fill it with the following lines.

.. code::

    [lsst-ts]
    name=LSST Telescope and Site packages - $basearch
    baseurl=https://repo-nexus.lsst.org/nexus/repository/ts_yum/releases
    failovermethod=priority
    enabled=1
    gpgcheck=0

**Requirements**

* opensplice, installed via LSST Nexus yum repo

.. code::

  yum install OpenspliceDDS

.. code::

  conda install -c lsstts ts_salobj[=version]

Optionally you can install a particular version otherwise it installs the latest release.

Another way to install ts-salobj is to use ``pip``.

.. code::

    pip install ts-salobj[=version]

Either way, the final step is to source the following file.

.. prompt:: bash

    source $OSPL_HOME/release.com

This activates the opensplice DDS system.
