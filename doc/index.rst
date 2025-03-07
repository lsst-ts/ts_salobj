.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj:

##############
lsst.ts.salobj
##############

.. image:: https://img.shields.io/badge/GitHub-gray.svg
    :target: https://github.com/lsst-ts/ts_salobj
.. image:: https://img.shields.io/badge/Jira-gray.svg
    :target: https://jira.lsstcorp.org/issues/?jql=project%3DDM%20AND%20labels%3Dts_salobj

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.
``ts_salobj`` SAL communication uses Kafka.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527

.. _lsst.ts.salobj-using:

Using lsst.ts.salobj
====================

.. toctree::
    configuration
    installation
    salobj_cscs
    sal_scripts
    :maxdepth: 2

Important Classes
-----------------

* `BaseCsc` and `ConfigurableCsc` are subclasses of `Controller` that supports the standard CSC summary states and state transition commands.
  The latter also supports configuration via yaml files that are validated against a schema.
  See :ref:`Writing a CSC<lsst.ts.salobj-writing_a_csc>` for more information.
  It is important to call `BaseCsc.close` when done with the CSC; `BaseCsc.amain` does this automatically, but in other cases see :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `Controller` provides the capability to output SAL telemetry and event topics and receive SAL commands.
  Every Python SAL component that is not a Commandable SAL Component (CSC) should be a subclass of `Controller`.
  See :ref:`Writing a Controller<writing_a_controller>` for more information.
  Note that it is important to close the `Controller` when you are finished.
  See :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `Remote` supports listening to other SAL components; it can receive events and telemetry and issue commands.
  If your SAL component needs to do this then it should create one `Remote` for each SAL component it wants to interact with.
  See the example above.
* `Domain` contains the origin (for the private_origin field of topics), default identity and weak links to all SalInfo objects that use the domain.
  See :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `BaseScript` is a base class for :ref:`Python SAL Scripts<lsst.ts.salobj_python_sal_scripts>`.
* `AsyncS3Bucket` is a class for asynchronously uploading and downloading files to/from s3 buckets.

Examples:

* `TestCsc` is an example of a fairly simple SAL CSC, though it is slightly unusual because it is intended for use in unit tests.
  In particular, it does not output telemetry at regular intervals.
* `TestScript` is an example of a trivial :ref:`Python SAL Script<lsst.ts.salobj_python_sal_scripts>`.

.. _lsst.ts.salobj-read-loop:

Read Loop
---------

When instantiating a `Remote` or a `Controller` (and its child classes) for a component, salobj instantiates a `SalInfo` class that holds the consumer and producer objects.
This allows salobj to batch reads and writes, by centralizing these resources in a single class.

For the data consumption, each instance of `SalInfo` creates a background "read loop", which is responsible for retrieving data from the middleware, deserializing it and distributing it to the data readers.
In practice, this means that all the data consumed by a component (`Remote` or `Controller`) is retrieved by a single background loop.

With the migration from DDS to Kafka for the middleware the workload required to pool, deserialize and distribute the data was lifted into the application layer.
For DDS, this was mostly done by the OpenSplice daemon, which would use a shared memory space to distribute the data to the application space.
The way Kafka operates is somewhat similar to running the system with the single process mode in DDS.

In practice, most applications are not impacted by this, either because they have small workloads in the first place or because they are not reading too much data.
However, we do have some applications that either have high workload, read a lot of data or both; examples being the LOVE-producer (especially for M1M3), the EUIs in general (which are rendering the user interface) and potentially some Scripts or CSCs like the MTMount and M2.
In those cases, usually what happens is the application is not able to keep up with the data stream; data starts to pile up in the read loop and the different read queues.
Since all data is read by a single read-loop, this means that `Remote`'s that are suffering from high load will get backed off on all data traffic, not only on the high-throughput data.
This can end up causing issues like commands timing out or timeout waiting for a particular asynchronous event.

In order to mitigate this issue with Kafka we introduced the `KafkaConsumer` class.
This class isolates all topic consumption routines, it is designed to be executed in a separate process altogether, using a Process Queue to pass data from one process into another.
The read loop in `KafkaConsumer` handles the communication with Kafka and data deserialization.
However, offloading this workload alone into a separate process will not solve all the issues.
The data still needs to be passed over into the application process which then needs to distribute it.
If the overall data throughput is high, the main application process will still have issues handling the load.

We are now facing a situation where the application is consuming more data then it has capacity to process.
In order to resolve this issue we need to apply some level of (selective) throttling.
We can take advantage of the fact that consuming and deserialization is done on a separate process to apply additional processing and filtering of messages.
There are some benefits from implementing throttling at salobj level, as opposed to relying on the middleware to handle overloaded conditions like with DDS.
For example, we can take advantage of our knowledge about how the system is supposed to work in how throttling will be implemented.
The most critical things we need to take into account are;

#. Commands, Command Acknowledgements and Events are asynchronous and (mostly) mission critical and, by default, should not be throttled.
#. Telemetry is published at a fixed rate ranging from 0.5Hz to 50Hz and are less critical.
   As such they are the main candidate for being throttled.

However there are some special conditions that may require us to be able to fine tune throttling.
For instance, some events like ``logMessage`` is not mission critical and could be throttled.
There might also be situations where a telemetry topic needs to be monitored without throttling for reliability.

It is therefore possible to configure throttling settings using `ThrottleSettings`.
The default values are designed to work for the majority of the situations.
If one needs to modify any of the defaults, you can customize it using a yaml file.
The file must have the same parameters as `ThrottleSettings` and the location of the file can be configured using the `LSST_KAFKA_THROTTLE_SETTINGS` environment variables.

.. _lsst.ts.salobj-fine-tune-read-loop:

Fine Tunning the Read Loop
^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to fine tune the read loop by a combination of two arguments in the `Remote` class; `num_messages` and `consume_messages_timeout`.
By default these parameters are set to work for the majority of use cases, e.g.; normal CSC and SAL Script operations.
However, in some applications, it might be necessary to tune the read loop to improve handling of high throughput topics.

If dealing with a high volume of data one might want to increase `num_messages` and reduce `consume_messages_timeout`.
This allows the read loop to batch process a higher number of messages at each loop.
However, when increasing the number of messages processed at every loop, this might increase the read latency as the loop only processes the messages if it received the number of messages requested or `consume_messages_timeout` has passed.
When trying to optimize the read loop it is import to test a combination of values for these parameters.

.. _lsst.ts.salobj-throttling:

Throttling
^^^^^^^^^^

As mentioned above, throttling might be important in situations where the data throughput is larger than an application is able to consume and still perform its intended workload.
For CSCs this will seldom be an issue as they are mostly, with some small exceptions, producers of telemetry and events.

If a particular CSC consumes data from other CSCs and must not be throttled (even to the expense of its own internal workload) it is possible to disable throttling altogether.
To do that create a yaml file with the follow content:

.. code-block:: yaml
   :name: disable-throttling-config

   enable_throttling: False

Ensure the environment variable LSST_KAFKA_THROTTLE_SETTINGS is set with the path to the file.

If you want to ensure a particular telemetry topic is not throttled, you can add its name to the `exclude_topics`:

.. code-block:: yaml
   :name: exclude-topics-throttling-config

   exclude_topics:
     - lsst.sal.Test.scalars

It is also possible to add an event topic to the list of throttled topics using `include_topics`:

.. code-block:: yaml
   :name: include-topics-throttling-config

   include_topics:
     - lsst.sal.Test.logevent_scalars

By default, all telemetry topics are included and all events are excluded.

The throttling algorithm works as follows:

- In the read loop, keep track of how many messages of each type are received.
  
- After a certain number of messages are consumed (e.g. 1000 messages), analyze the data stream.

  The analysis consists of:

  - Check if the throughput is larger than `ThrottleSettings.throughput_measurement_warn_threshold`.

    If not, ignore throttling, continue otherwise.

  - Check if the size of the read queue surpasses `ThrottleSettings.auto_throttle_qsize_limit`.

    If not, ignore throttling, continue otherwise.

  - Calculate throttling values based on how many messages each topic received and the size of the read queue.

    Topics that received more messages will receive larger penalties.

    The larger the read queue, the larger throttle will be.

    Throttle values are scaled down based on `ThrottleSettings.auto_throttle_qsize_limit`, the larger the limit the lower the throttle.

    Throttle values can vary from 1 (no throttle) to `ThrottleSettings.max_throttle`.
    It represents how many messages will be discarded for each message kept.
    - A value of 1 means all messages are kept.
      
    - A value of 2 means we keep every other message.
      This would essentially half the received throughput for a particular topic, e.g., if a topic is published at 10Hz it would be internally scaled down to 5Hz. 

    - A value of 10 means we keep 1 for every 10 messages, effectively converting an 100Hz stream into a 1Hz stream.

- Whenever the throttling analysis is executed the count resets and will repeat following the same condition specified above.

- For each pass (with the exception of the first one) the change in throttle can change only by as much as `ThrottleSettings.max_throttle_change`.
  This is to avoid throttling fluctuating rapidly as a result of more resources being freed on the application level to handle the reduced message load.

- If the throttle analysis is executed more than `ThrottleSettings.no_throttle_pass_adjust` without triggering any of the thresholds, it will reset throttle.

  This is to avoid situations where there is a burst of messages causing several messages to be received at once by a client.
  This could happen, for instance, after a network glitch.
  In this case, throttle could be triggered to handle the increase in incoming messages, followed by a return to normal levels that would not trigger throttling analysis, thus not allowing the client to adjust throttling levels.

All the `ThrottleSettings` parameters mentioned above can be configured using an yaml file set to `LSST_KAFKA_THROTTLE_SETTINGS`.

.. _lsst.ts.salobj-wrap-main-process:

Wrap Main Process
^^^^^^^^^^^^^^^^^

Because `SalInfo` is now spawning a separate process, running an executable now requires the main process to wrap its call with a:

.. code-block:: py

   if __name__ == "__main__":
       main()

For most repositories, that are using conda/pypi, this is not going to be an issue as it already handles that when creating the executable.
However, most SAL Scripts are not handling that properly and will need to be updated.

.. _lsst.ts.salobj-cleanup:

Cleanup
-------

It is important to call `Controller.close` or `Domain.close` when done with any controller or domain you construct, unless your process is exiting.
Note that closing a `Domain` automatically cleans up the resources used by all `Remote`\s constructed using that domain.
You may also close `Remote`\ s directly, if you like, and if you close all `Remote`\ s then there is no need to also close the `Domain`.

`Controller`, `Domain`, and `Remote` can all be used as asynchronous context managers to call ``close`` automatically.
For example:

  .. code-block:: python

    # If you have a controller or CSC:
    async with TestCsc(index=1) as csc:
        dome = Remote(domain=csc.domain, name="Test", index=0)

    # If you don't have a controller or CSC:
    async with Domain() as domain:
        dome = Remote(domain=domain, name="Test", index=1)

.. _lsst.ts.salobj-contributing:

Contributing
============

``lsst.ts.salobj`` is developed at https://github.com/lsst-ts/ts_salobj.
You can find Jira issues for this module using `project=DM and labels=ts_salobj <https://jira.lsstcorp.org/issues/?jql=project%3DDM%20AND%20labels%3Dts_salobj>`_.


.. _lsst.ts.salobj-pyapi:

Python API reference
====================

.. automodapi:: lsst.ts.salobj
    :no-main-docstr:
    :skip: StandardValidator
.. automodapi:: lsst.ts.salobj.topics
    :no-main-docstr:

Version History
===============

.. toctree::
    version_history
    :maxdepth: 1
