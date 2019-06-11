.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj:

##############
lsst.ts.salobj
##############

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527

.. _lsst.ts.salobj-using:

Using lsst.ts.salobj
====================

.. toctree::
    salobj_cscs
    sal_scripts
    :maxdepth: 1

**Important classes:**

* `BaseCsc` and `ConfigurableCsc` are subclasses of `Controller` that supports the standard CSC summary states and state transition commands.
  The latter also supports configuration via yaml files that are validated against a schema.
  See :ref:`Writing a CSC<lsst.ts.salobj-writing_a_csc>` for more information.
  It is important to call `BaseCsc.close` when done with the CSC; `BaseCsc.main` does this automatically, but in other cases see :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `Controller` provides the capability to output SAL telemetry and event topics and receive SAL commands.
  Every Python SAL component that is not a Commandable SAL Component (CSC) should be a subclass of `Controller`.
  See :ref:`Writing a Controller<writing_a_controller>` for more information.
  Note that it is important to close the `Controller` when you are finished.
  See :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `Remote` supports listening to other SAL components; it can receive events and telemetry and issue commands.
  If your SAL component needs to do this then it should create one `Remote` for each SAL component it wants to interact with.
  See the example above.
* `Domain` contains the dds domain participant (which includes a cache of topic data) and quality of service objects for the various categories.
  There should be one `Domain` per process or unit test method.
  `Controller` creates and manages a `Domain`, but if you have no controller (as may be the case for some unit tests and Jupyter notebooks) then you will have to create and manage it yourself.
  See :ref:`Cleanup<lsst.ts.salobj-cleanup>` for more information.
* `BaseScript` is a base class for :ref:`Python SAL Scripts<lsst.ts.salobj_python_sal_scripts>`.

Examples:

* `TestCsc` is an example of a fairly simple SAL CSC, though it is slightly unusual because it is intended for use in unit tests.
  In particular, it does not output telemetry at regular intervals.
* `TestScript` is an example of a trivial :ref:`Python SAL Script<lsst.ts.salobj_python_sal_scripts>`.

.. _lsst.ts.salobj-cleanup:

**Cleanup:**

It is important to call `Controller.close` or `Domain.close` when done with it (and this automatically closes the resources used by `Remote`).
`Controller` creates and manages its own `Domain` but if you don't have a `Controller` then you will have to create and manage one yourself.
Both `Controller` and `Domain` can be used as asynchronous context managers to call ``close`` automatically.
Here are some examples::

    # if you have a controller or CSC
    async with BaseCsc(name="ATDomeTrajectory", index=0) as dome_trajectory:
        dome = Remote(domain=dome_trajectory.domain, name="ATDome", index=0)

    # if you don't have a controller or CSC
    async with Domain() as domain:
        dome = Remote(domain=dome_traj.domain, name="ATDome", index=0)

.. _lsst.ts.salobj-contributing:

Contributing
============

``lsst.ts.salobj`` is developed at https://github.com/lsst-ts/ts_salobj.
You can find Jira issues for this module under the `ts_salobj <https://jira.lsstcorp.org/issues/?jql=project%20%3D%20DM%20AND%20component%20%3D%20ts_salobj>`_ component.

.. _lsst.ts.salobj-pyapi:

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
