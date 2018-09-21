.. py:currentmodule:: salobj

.. _salobj:

######
salobj
######

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527

A SAL component receives commands from other SAL components and outputs information as telemetry and log events.
This capability is made available in `salobj.Controller`.

In addition, a SAL component may communication with one or more remote components by reading telemetry and log events from them and perhaps sending commands to them.
This capability is made available in `salobj.Remote`.

How to Make a SAL Component
===========================

Create a class containing one `salobj.Controller` attribute to receive the commands for that component and output telemetry and log events.
If your component communicates with remote SAL components then add a `salobj.Remote` attribute for each remote component.
Define a method to implement each command your component supports.
Assign that method as a callback to the appropriate ``cmd_<command_name>`` of the controller.

The controller will send a "command succeed" acknowledgement when the command method terminates normally, or a "command failed" acknowledgement if the command method raises an exception (as long as it is a subclass of ``Exception``).
Each command method should return fairly quickly.
If the command needs to start a slow or long-term operation (such as a telescope tracking) then you should implement that code in a coroutine (a method defined by `async def`) and start it from the command method by calling `asyncio.ensure_future(coroutine)`.
The command will be reported as finished when the command method finishes, and the slow or long-term operation can continue at its own pace.

See `salobj.test_utils.TestComponent` for an example.

Note that we plan to offer a high level class for SAL Components that handles some of the above for you, including the standard state transitions for "CSC"s.

Python API reference
====================

.. automodapi:: salobj
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: salobj.topics
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: salobj.test_utils
    :no-main-docstr:
    :no-inheritance-diagram:
