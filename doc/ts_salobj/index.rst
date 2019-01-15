.. py:currentmodule:: lsst.ts.salobj

.. _ts_salobj:

#########
ts_salobj
#########

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527

Important classes:

* `BaseCsc` is a subclass of `Controller` that supports the standard CSC summary states and state transition commands.
  See :ref:`Writing a CSC<writing_a_csc>` for more information.
* `Controller` provides the capability to output SAL telemetry and event topics and receive SAL commands.
  Every Python SAL component that is not a Commandable SAL Component (CSC) should be a subclass of `Controller`.
  See :ref:`Writing a Controller<writing_a_controller>` for more information.
* `Logger` supports writing to a standard Python logger and outputting the result as a `logMessage` SAL event.
  `Controller` is a subclass of `Logger` so all controllers have logging capability.
  For example: ``self.log.warning("example warning message")``.
* `Remote` supports listening to other SAL components; it can receive events and telemetry and issue commands.
  If your SAL component needs to do this then it should create one `Remote` for each SAL component it wants to interact with.
  For example: ``self.electrometer1 = salobj.Remote(SALPY_Electrometer, index=1)``

`test_utils.TestCSC` is an example of a fairly simple SAL CSC, though it is slightly unusual because it is intended for use in unit tests.
In particular, it does not output telemetry at regular intervals.


Python API reference
====================

.. automodapi:: lsst.ts.salobj
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: lsst.ts.salobj.topics
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: lsst.ts.salobj.topics.base_topic
    :no-main-docstr:
    :no-inheritance-diagram:
