.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj:

##############
lsst.ts.salobj
##############

Object-oriented Python interface to `Service Abstraction Layer`_ (SAL) components that uses asyncio for asynchronous communication.
``ts_salobj`` SAL communication uses the `dds Python library`_, which is part of `Vortex OpenSplice`_.
You may use the free community edition or the licensed edition of OpenSplice.

.. _Service Abstraction Layer: https://docushare.lsstcorp.org/docushare/dsweb/Get/Document-21527
.. _dds Python library: http://download.ist.adlinktech.com/docs/Vortex/html/ospl/PythonDCPSAPIGuide/index.html
.. _Vortex OpenSplice: https://istkb.adlinktech.com/article/vortex-opensplice-documentation/

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
* `Domain` contains the dds domain participant (which includes a cache of topic data) and quality of service objects for the various categories.
  There should be only one `Domain` per process or unit test method, if practical, though some unit tests create a few more.
  `Controller` creates and manages a `Domain`, but if you have no controller and wish to construct one or more `Remote`\s then you will have to create and manage a `Domain` yourself.
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

Both `Controller` and `Domain` can be used as asynchronous context managers to call ``close`` automatically.
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
You can find Jira issues for this module using `labels=ts_salobj <https://jira.lsstcorp.org/issues/?jql=project%20%3D%20DM%20AND%20labels%20%20%3D%20ts_salobj>`_.


.. _lsst.ts.salobj-pyapi:

Python API reference
====================

.. automodapi:: lsst.ts.salobj
    :no-main-docstr:
.. automodapi:: lsst.ts.salobj.topics
    :no-main-docstr:

Version History
===============

.. toctree::
    version_history
    :maxdepth: 1
