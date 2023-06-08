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

The most convenient way to develop salobj-based software is to run a local Kafka server, as follows:

* If running salobj code in a Docker image:

  * Make sure Docker has a network named ``ts_salobj_default``::

      docker network ls

    If not, create it with::

      docker network create ts_salobj_default

  * Run your Docker image with this option, to make this network available::

    --network=ts_salobj_default

  * Leave environment variables ``LSST_KAFKA_BROKER_ADDR`` and ``LSST_SCHEMA_REGISTRY_URL`` undefined.
    The default values assume you are running salobj code inside a docker image.

* If running salobj code directly on your computer, instead of inside a Docker image:

  * Set the following environment variables::

      export LSST_KAFKA_BROKER_ADDR="127.0.0.1:9092"
      export LSST_SCHEMA_REGISTRY_URL="http://schema-registry:8081"

* To start and stop Kafka, use the following bash/zsh functions::

    function kafka_run() {
        pushd <path to ts_salobj>
        docker-compose up -d zookeeper broker schema-registry
        popd
    }

    function kafka_stop() {
        pushd <path to ts_salobj>
        docker-compose rm --stop --force broker schema-registry zookeeper
        popd
    }

  Note that the docker-compose commands **must** be run in the ts_salobj directory.

Additional Configuration
========================

To run code other than unit tests, you will also need to set the following environment variables::

* ``LSST_SITE``: set to "test" or whatever site you want to load configuration files for.
* ``LSST_TOPIC_SUBNAME``: set to "test" or any short-ish string of characters ``[a-zA-Z0-9._]``.

See :ref:`lsst.ts.salobj-configuration_environment_variables` for more information.

Unit tests must set these two environment variables (rather than assuming the user has set them).
`BaseCscTestCase` sets both environment variables for you; but if not using it, you must set them yourself.
Each test should run with a different value of  ``LSST_TOPIC_SUBNAME``.
To do this, we recommend calling `set_random_topic_subname` in ``setUp`` or similar.
