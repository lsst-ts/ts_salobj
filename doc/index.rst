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
``ts_salobj`` SAL communication use Kafka.

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
