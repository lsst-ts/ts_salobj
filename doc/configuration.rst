.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj-configuration:

#####################
Configuring ts_salobj
#####################

.. _lsst.ts.salobj-configuration_environment_variables:

Environment Variables
---------------------

ts_salobj reads the following environment variables:

Used by `SalInfo`:

* ``LSST_TOPIC_SUBNAME`` (required): a component of Kafka topic names and schema namespaces.
  This allows experimental code to not interfere with production code, and unit tests to not interfere with each other.
  Each `Remote` and `Controller` (hence ``CSC``) can have a different sub-namespace.

* ``LSST_DDS_ENABLE_AUTHLIST`` (optional): if set to "1" enable authlist-based command authorization.
  If "0" or undefined, do not enable authorization.

* ``LSST_KAFKA_BROKER_ADDR`` (optional): the address of the Kafka broker.
  Defaults to the value used by `kafka-aggregator`_, for unit tests.

* ``LSST_SCHEMA_REGISTRY_URL`` (optional): url of the Confluent schema registry.
  Defaults to the value used by `kafka-aggregator`_, for unit tests.

Used by `ConfigurableCsc`:

* ``LSST_SITE`` (required): the site, e.g. "summit", "base", or "tucson".
  Used to select the site-specific configuration file, if it exists, to supplement ``_init.yaml``.
  For example if LSST_SITE="summit" then the default CSC configuration (configurationOverride="") is given by reading ``_init.yaml`` followed by ``_summit.yaml`` (if it exists).

Used by `AsyncS3Bucket`:

* ``S3_ENDPOINT_URL``: The endpoint URL for the S3 server, e.g. ``http://foo.bar:9000``.
  You must specify a value in order to use an S3 service that is not part of Amazon Web Services (AWS).
  Eventually we hope that ``endpoint_url`` can be defined in ``~/.aws/config``.
  Once that is supported you can leave this environment variable unset, and we can deprecate it.

.. _lsst.ts.salobj-configuration_other:

Required LSST Packages
----------------------

ts_salobj requires the following LSST packages:

* `kafka-aggregator`_ to provide a Kafka system for running unit tests.
* `ts_utils`_ for time functions and such.
* `ts_xml`_ for SAL interfaces.

.. _kafka-aggregator: https://kafka-aggregator.lsst.io/
.. _ts_utils: https://github.com/lsst-ts/ts_utils
.. _ts_xml: https://github.com/lsst-ts/ts_xml
