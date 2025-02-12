.. py:currentmodule:: lsst.ts.salobj

############
Installation
############

Install ts_salobj
=================

You may install ts_salobj using conda or pip::

    conda install -c lsstts ts-salobj[=version]

or::

    pip install ts-salobj[==version]


Run a Local Kafka Server
========================

The most convenient way to develop salobj-based software is to run a local Kafka server in Docker, using the docker-compose file, as follows:

* To start Kafka::

    docker-compose -f <path-to-ts_salobj>/docker-compose.yaml up -d

* To stop kafka and delete its data ("log files")::

    docker-compose -f <path-to-ts_salobj>/docker-compose.yaml rm --stop --force

* Consider making aliases for these two commands, e.g.::

    alias kafka_run="docker-compose -f <path-to-ts_salobj>/docker-compose.yaml up -d"

    alias kafka_stop="docker-compose -f <path-to-ts_salobj>/docker-compose.yaml rm --stop --force"

To use this Kafka server, configure salobj as follows:

* If running salobj code in a Docker image:

  * Run your Docker image with the following option, to make the ``kafka`` network (the network used by the docker-compose file) available::

      --network=kafka

  * Leave environment variables ``LSST_KAFKA_BROKER_ADDR`` and ``LSST_SCHEMA_REGISTRY_URL`` undefined.
    The default values assume you are running salobj code inside a docker image.

* If running salobj code directly on your computer, instead of inside a Docker image:

  * Set the following environment variables::

      export LSST_KAFKA_BROKER_ADDR="localhost:9092"
      export LSST_SCHEMA_REGISTRY_URL="http://localhost:8081"


Additional Configuration
========================

To run code other than unit tests, you will also need to set the following environment variables::

    export LSST_SITE=test  # or whatever site you want to load configuration files for
    export LSST_TOPIC_SUBNAME=test  # or any short-ish string of characters [a-zA-Z0-9._]

See :ref:`lsst.ts.salobj-configuration_environment_variables` for more information.

Unit tests must set these two environment variables (rather than assuming the user has set them).
`BaseCscTestCase` sets both environment variables for you; but if not using it, you must set them yourself.
Each test should run with a different value of  ``LSST_TOPIC_SUBNAME``.
To do this, we recommend calling `set_test_topic_subname` in ``setUp`` or similar.
