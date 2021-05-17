.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj-configuration:

#####################
Configuring ts_salobj
#####################

.. _lsst.ts.salobj-configuration_environment_variables:

Environment Variables
---------------------

ADLink OpenSplice is configured using environment variables described in `ts_ddsconfig environment variables`_.

ts_salobj reads (or, in the case of ``OSPL_MASTER_PRIORITY`` writes) the following environment variables:

Used by `Domain` (indirectly):

* ``OSPL_MASTER_PRIORITY`` (optional) sets the priority for which durability service is the master.
  Described in `ts_ddsconfig environment variables`_.
  Temporarily set to 0 by `BaseScript` while constructing its `Domain` to prevent SAL scripts from becoming master
  (though this only affects unit tests; in production SAL scripts use a shared memory daemon for their durability service).
  Constant ``lsst.ts.salobj.MASTER_PRIORITY_ENV_VAR`` is available to make this easier to set from Python.

Used by `SalInfo`:

* ``LSST_DDS_PARTITION_PREFIX`` (required): a prefix for DDS partition names.
  This is read by `SalInfo` so that different instances of `SalInfo` (thus different `Remote`\ s and `Controller`\ s)
  can communicate with different DDS partitions, even though all share the same `Domain`.
  See `ts_ddsconfig environment variables`_ for details.
* ``LSST_DDS_DOMAIN`` (deprecated): a deprecated alias for ``LSST_DDS_PARTITION_PREFIX``
  that is used if ``LSST_DDS_PARTITION_PREFIX`` is not defined.
* ``LSST_DDS_HISTORYSYNC`` (optional): time limit (sec) for waiting for historical (late-joiner) data.
  If, and only if, you are running DDS without a durability service then set this negative to avoid waiting for historical data.

Used by `AsyncS3Bucket`:

* ``S3_ENDPOINT_URL``: The endpoint URL for the S3 server, e.g. ``http://foo.bar:9000``.
  You must specify a value in order to use an S3 service that is not part of Amazon Web Services (AWS).
  Eventually we hope that ``endpoint_url`` can be defined in ``~/.aws/config``.
  Once that is supported you can leave this environment variable unset, and we can deprecate it.

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
