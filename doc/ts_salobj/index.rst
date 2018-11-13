.. py:currentmodule:: lsst.ts.salobj

.. _ts_salobj:

#########
ts_salobj
#########

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527

The main class in salobj is `BaseCsc`.
Create a subclass of this in order to make a Commandable SAL Component (CSC).
This is described in more detail below and in the doc string for `BaseCsc`.

A SAL component receives commands from other SAL components and outputs information as telemetry and log events.
This capability is made available in `Controller`, and `BaseCsc` provides one of these as attribute ``controller``.

In addition, a SAL component may communication with one or more remote components by reading telemetry and log events from them and perhaps sending commands to them.
This capability is made available in `Remote`, and if your CSC needs this then you must construct these yourself.

How to Make a Standard Commandable SAL Component (CSC)
======================================================

Create a subclass of `BaseCsc`.
Follow the instructions in the doc string for that class, including adding a ``do_<name>`` method for each non-standard command your CSC supports.
The ``do_<name>`` method is called automatically when the ``<name>`` command is seen, with one argument: a `topics.CommandIdData` object containing the command ID number and the command data.
Each command is automatically acknowledged as successful if the ``do_<name>`` method succeeds, or as failed if the ``do_<name>`` method raises an exception.

If the command needs to start a slow or long-term operation (such as a telescope tracking) then you should implement that code in a coroutine (a method defined by ``async def``) and start it from the command method by calling ``asyncio.ensure_future(coroutine)``.
The command will be reported as finished when the command method finishes, and the slow or long-term operation can continue at its own pace.

If your component communicates with remote SAL components then add a `Remote` attribute for each remote component.
Use the remote attribute to listen to events and telemetry from that remote component and issue commands to it.

`test_utils.TestCSC` is an example of a simple SAL CSC.
However, unlike a standard CSC, `test_utils.TestCSC` allows you to start up in any state, which can simplify testing.


Python API reference
====================

.. automodapi:: lsst.ts.salobj
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: lsst.ts.salobj.topics
    :no-main-docstr:
    :no-inheritance-diagram:
.. automodapi:: lsst.ts.salobj.test_utils
    :no-main-docstr:
    :no-inheritance-diagram:
