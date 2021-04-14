.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj-configuration:

#####################
Configuring ts_salobj
#####################

.. _lsst.ts.salobj-configuration_environment_variables:

Environment Variables
---------------------

ts_salobj uses the following environment variables to configure OpenSplice:

Used by `Domain` (indirectly):

* ``ADLINK_LICENSE`` points to directory containing your `Vortex OpenSplice`_ license.
  Required if using the licensed version of `Vortex OpenSplice`_; ignored otherwise.
  Example value: ``/opt/ADLINK/Vortex_v2/Device/VortexOpenSplice/6.10.3/HDE/x86_64.linux/etc``
* ``LSST_DDS_DOMAIN_ID`` (optional) is used to set the DDS domain: an integer.
  See `ts_ddsconfig environment variables`_ for details.
* ``OSPL_HOME`` (required) directory of the `Vortex OpenSplice`_ software.
  This directory should contain subdirectories ``bin``, ``include``, ``lib``, etc.
  Example: ``/opt/OpenSpliceDDS/V6.9.0/HDE/x86_64.linux``.
* ``OSPL_MASTER_PRIORITY`` (optional) is used to set the Master Priority in ts_sal 4.2 and later.
  Described in `ts_ddsconfig environment variables`_.
  Temporarily set to 0 by `BaseScript` while constructing its `Domain` to prevent SAL scripts from becoming master.
  Constant ``lsst.ts.salobj.MASTER_PRIORITY_ENV_VAR`` is available to make this easier to set from Python.
* ``OSPL_URI`` (required) points to the main DDS configuration file.
  Our configuration files are in `ts_ddsconfig`_.

Used by `SalInfo`:

* ``LSST_DDS_PARTITION_PREFIX`` (required): a prefix for DDS partition names.
  This is read by `SalInfo` so that different instances of `SalInfo` (thus different `Remote`\ s and `Controller`\ s) can communicate with different DDS partitions, even though all share the same `Domain`.
  See `SalInfo` for DDS partition name details.
* ``LSST_DDS_DOMAIN`` (deprecated): a deprecated alias for ``LSST_DDS_PARTITION_PREFIX`` that is used if ``LSST_DDS_PARTITION_PREFIX`` is not defined.
* ``LSST_DDS_HISTORYSYNC`` (optional): time limit (sec) for waiting for historical (late-joiner) data.
  If, and only if, you are running DDS without a durability service then set this negative to avoid waiting for historical data.
  (This variable is not described in the ts_ddsconfig user guide because it is not used to configure OpenSplice.)

Used by `AsyncS3Bucket`:

* ``S3_ENDPOINT_URL``: The endpoint URL for the S3 server, e.g. ``http://foo.bar:9000``.
  You must specify a value in order to use an S3 service that is not part of Amazon Web Services (AWS).
  Eventually we hope that ``endpoint_url`` can be defined in ``~/.aws/config``.
  Once that is supported you can leave this environment variable unset, and we can deprecate it.

There are many more environment variables that configure OpenSplice;
see `ts_ddsconfig environment variables`_ for details.

.. _lsst.ts.salobj-configuration_other:

Other Configuration
-------------------

In addition to the environment variables described above, you will need the following Python packages:

* `ts_ddsconfig`_ for OpenSplice DDS configuration.
* `ts_idl`_ for the IDL files that define SAL topic schemas, and associated enum modules.
* `ts_sal`_ to build IDL files and to run ts_salobj unit tests.

DDS topic schemas are defined by ``OMG IDL`` files, which are contained in the ``idl`` directory of the `ts_idl`_ package.
You may generate new IDL files using the ``make_idl_files.py`` command-line script in the `ts_sal`_ package.

.. _Vortex OpenSplice: https://istkb.adlinktech.com/article/vortex-opensplice-documentation/
.. _ts_ddsconfig: https://github.com/lsst-ts/ts_ddsconfig
.. _ts_ddsconfig environment variables: https://ts-ddsconfig.lsst.io/#environment-variables-in-ospl-configuration-files
.. _ts_idl: https://github.com/lsst-ts/ts_idl
.. _ts_sal: https://github.com/lsst-ts/ts_sal
