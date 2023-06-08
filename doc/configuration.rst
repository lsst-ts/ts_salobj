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

* ``LSST_DDS_ENABLE_AUTHLIST`` (optional): set to "1" enable authlist-based command authorization.
  Set to "0" or leave undefined to disable authlist-based command authorization.
  In the long run we intend to eliminate this environment variable and always enable authlist-based command authorization.

* ``LSST_KAFKA_BROKER_ADDR`` (optional): the address of the Kafka broker.
  If you are running Kafka locally, using the docker compose file, then set as follows:

  * Leave it blank or set it to ``broker:29092`` (the default), for running unit tests within a Docker container.
  * ``127.0.0.1:9092`` for running unit tests directly on your computer.

* ``LSST_SCHEMA_REGISTRY_URL`` (optional): url of the Confluent schema registry.
  If you are running Kafka locally, using the docker compose file, then set as follows:

  * Leave blank or set to ``http://schema-registry:8081`` (the default) for running unit tests within a Docker container.
  * ``127.0.0.1.8081`` for running unit tests directly on your computer.

* ``LSST_TOPIC_SUBNAME`` (required): a component of Kafka topic names and schema namespaces.
  Use a value of "sal" for production code, and any other value for experimental code and unit tests.
  This allows experimental code to not interfere with production code, and unit tests to not interfere with each other.
  Each `Remote` and `Controller` (hence ``CSC``) can have a different sub-namespace.

Used by `ConfigurableCsc`:

* ``LSST_SITE`` (required): the site.
  Used to select the site-specific configuration file, if one exists, to supplement ``_init.yaml``.
  Standard values include "summit", "base", and "tucson".
  For example if LSST_SITE="summit" then the default CSC configuration (configurationOverride="") is given by reading ``_init.yaml`` (which must exist), followed by ``_summit.yaml`` (if it exists).

Used by `AsyncS3Bucket`:

* ``S3_ENDPOINT_URL``: The endpoint URL for the S3 server, e.g. ``http://foo.bar:9000``.
  You must specify a value in order to use an S3 service that is not part of Amazon Web Services (AWS).
  Eventually we hope that ``endpoint_url`` can be defined in ``~/.aws/config``; if that is ever supported, we can deprecate this environment variable.

.. _lsst.ts.salobj-configuration_other:
