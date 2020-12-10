############
Installation
############

Install ADLink OpenSplice
=========================

You may install the OpenspliceDDS package from the LSST Nexus yum repo
(as of 2020-12 this repository only supports CentOS 7), as follows:

* Add configuration file ``/etc/yum.repos.d/lsst-ts.repo`` to have yum locate the repository::

   [lsst-ts]
   name=LSST Telescope and Site packages - $basearch
   baseurl=https://repo-nexus.lsst.org/nexus/repository/ts_yum/releases
   failovermethod=priority
   enabled=1
   gpgcheck=0

* Install the file using yum::

   yum install OpenspliceDDS

Configure ADLink OpenSplice
===========================

Set environment variable ``OSPL_HOME`` to the linux distribution within the installed OpenSplice.
In our Docker images it is something like ``/opt/OpenSpliceDDS/V6.10.0/HDE/x86_64.linux``.

Use ``OSPL_HOME`` to define the remaining environment variables needed by OpenSplice::

    source $OSPL_HOME/release.com

Install ts_salobj
=================

You may install ts_salobj using conda or pip::

    conda install -c lsstts ts-salobj[=version]

or::

    pip install ts-salobj[==version]
