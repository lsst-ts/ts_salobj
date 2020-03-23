.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj_sal_scripts:

SAL Scripts
###########

SAL scripts are programs that perform coordinated telescope and instrument control operations, such as "slew to a target and take an image", or "take a series of flats".
SAL scripts are similar to CSCs in that they communicate via SAL messages, but a SAL script is run once and then it quits, whereas CSCs may run for months at a time.
SAL scripts are typically written in Python; see :ref:`Python SAL Scripts<lsst.ts.salobj_python_sal_scripts>` for more information.

Technically a SAL script is any SAL component that supports the ``Script`` API defined in ``ts_xml`` and follows these rules:

* The script is a command-line executable that takes a single required command line argument: the index of the SAL component.
* When run, the script must start in the `lsst.ts.idl.enums.Script.ScriptState.UNCONFIGURED` state and output the ``description`` event.
* When the script is in the `lsst.ts.idl.enums.Script.ScriptState.UNCONFIGURED` state it can be configured with the ``configure`` command (and the command must be rejected in any other state):

    * If the ``configure`` command succeeds, the script must report the ``metadata`` event and state `lsst.ts.idl.enums.Script.ScriptState.CONFIGURED`.
    * If the ``configure`` command fails the script must report state `lsst.ts.idl.enums.Script.ScriptState.FAILED` and exit.
    
* Once the state is `lsst.ts.idl.enums.Script.ScriptState.CONFIGURED`, the script can have its group ID set with the ``setGroupId`` command (and the command must be rejected in any other state):

    * If the ``setGroupId`` command succeeds, the script must output a ``state`` event with the ``groupId`` field set to the new group ID.
      Note that the script state remains `lsst.ts.idl.enums.Script.ScriptState.CONFIGURED`.
      Thus the ``setGroupId`` command may be issued multiple times; this allows the script queue to set the group ID, clear it, then set it again.

* Once the group ID is set (not blank), the script can be run with the ``run`` command (which must be rejected if the state is not `lsst.ts.idl.enums.Script.ScriptState.CONFIGURED` or the group ID is blank):

    * When the script starts running it must report state `lsst.ts.idl.enums.Script.ScriptState.RUNNING`.
    * As the script starts starts cleaning up, it should report one of these states:

        * `lsst.ts.idl.enums.Script.ScriptState.ENDING` if the main execution succeeded (cleanup might still fail).
        * `lsst.ts.idl.enums.Script.ScriptState.STOPPING` if stopping by request.
        * `lsst.ts.idl.enums.Script.ScriptState.FAILING` if stopping because an error occurred.

    * When the ``run`` command finishes the script must exit, after reporting one of three states:

        * `lsst.ts.idl.enums.Script.ScriptState.DONE` on success
        * `lsst.ts.idl.enums.Script.ScriptState.STOPPED` if stopped by request
        * `lsst.ts.idl.enums.Script.ScriptState.FAILED` if an error occurred

* The script must also support the command line option ``--schema`` which prints the configuration schema to ``stdout`` and quits.
  This option ignores the index, but the index argument is still required.

`BaseScript` provides a base class for :ref:`Python SAL Scripts<lsst.ts.salobj_python_sal_scripts>`.

Script Packages
###############

All SAL scripts should go into the ``scripts`` directory of one of the following packages, so the `ScriptQueue` can find them:

* ``ts_standardscripts``: scripts that are approved for regular use.
  These must have :ref:`unit tests<lsst.ts.salobj_python_unit_test>` and will be subject to strict version control.
* ``ts_externalscripts``: scripts for experimentation and one-off tasks.

.. _lsst.ts.salobj_python_sal_scripts:

Python SAL Scripts
##################

Each :ref:`SAL Script<lsst.ts.salobj_sal_scripts>` written in Python should consist of three parts:

* The script file itself, as an executable file in an appropriate subdirectory of ``scripts/`` in ``ts_standardscripts`` or ``ts_externalscripts`` package.
* An implementation in the matching subdirectory of ``python/lsst/ts/standardscripts`` (or ``externalscripts``) in the same package.
  This almost always inherits from `BaseScript`.
  (Technically the implementation can be in the script file, but that makes it much more difficult to test the code or run it from a Jupyter notebook.)
* A unit test in the matching subdirectory of ``tests/``, whose name is ``test_`` followed by the name of the script file.

For example the ``SlewTelescopeIcrs`` script has the following files in ``ts_standardscripts``:

* The script file: ``scripts/auxtel/slew_telescope_icrs.py``
* The implementation: ``python/lsst/ts/standardscripts/auxtel/slew_telescope_icrs.py``
* The unit test: ``tests/auxtel/test_slew_telescope_icrs.py``

Python Script File
==================

The script file should just import the script and run ``amain``:

  .. code-block:: python

    #!/usr/bin/env python
    #...standard LSST boilerplate
    import asyncio

    from lsst.ts.standardscripts.auxtel import SlewTelescopeIcrs

    asyncio.run(SlewTelescopeIcrs.amain())

Make your script executable using ``chmod +x <path>``.

Python Script Implementation
============================

See ``python/lsst/ts/standardscripts/auxtel/test_slew_telescope_icrs.py`` in the ``ts_standardscripts`` package for an example.

The script implementation does the actual work.
Your script should be a subclass of `BaseScript` with the following methods (all required unless otherwise noted):

get_schema classmethod
----------------------

Return a jsonschema defining the configuration of your script.
See `BaseScript.get_schema` for details.

configure method
----------------

Configure your script using a configuration validated by ``get_schema``.
See `BaseScript.configure` for details.

Note that ``configure`` will always be called once before ``run`` and never again.
Thus if ``configure`` sets attributes needed by ``run``, there is no point to initializing those attributes in the constructor.

run method
----------

Perform the main work of the script.
See `BaseScript.run` for details.

If ``run`` needs to run a slow computation, either call ``await asyncio.sleep(0)`` occasionally to give other coroutines a chance to run (0 is sufficient to free the event loop), or run the computation in a thread using `run_in_executor`_ e.g.:

  .. code-block:: python

    def slow_computation(self):
        ...

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, slow_computation)

or if you wish to do other things while you wait:

  .. code-block:: python

    loop = asyncio.get_running_loop()
    thread_task = asyncio.create_task(loop.run_in_executor(None, slow_computation))

    # do other work here...
    # then eventually you must wait for the background task
    result = await thread_task

.. _run_in_executor: https://docs.python.org/3/library/asyncio-eventloop.html#id14

checkpoints
^^^^^^^^^^^

In your run method you may call ``await self.checkpoint(name_of_checkpoint)`` to specify a point at which users can pause or stop the script.
By providing a diferent name for each checkpoint you allow users to specify exactly where they would like the script to pause or stop.
In addition, each checkpoint is reported as the ``lastCheckpoint`` attribute of the ``state`` event, so providing informative names can be helpful in tracking the progress of a script.
We suggest you make checkpoint names fairly short, obvious and unique, but none of these rules is enforced.
If you have a checkpoint in a loop you may wish to modify the name for each iteration, e.g.:

  .. code-block:: python

    for iter in range(num_exposures):
        await self.checkpoint(f"start exposure {iter}")
        ...

This allows the user to pause or stop at any particular iteration, and makes the ``state`` event more informative.

cleanup method (optional)
-------------------------

When your script is ending, after ``run`` finishes, is stopped early, or raises an exception, ``BaseScript`` calls asynchronous method ``cleanup`` for final cleanup.
See `BaseScript.cleanup` for details.
In some sense ``cleanup`` is like the ``finally`` clause of a ``try/finally`` block.

The default implementation does nothing, but you are free to override it.
If your cleanup code cares about why the script is ending, examine ``self.state.state``; it will be one of:

* `lsst.ts.idl.enums.Script.ScriptState.ENDING`: the ``run`` method ran normally.
* `lsst.ts.idl.enums.Script.ScriptState.STOPPING`: the script was commanded to stop.
* `lsst.ts.idl.enums.Script.ScriptState.FAILING`: the ``run`` method raised an exception.

If your cleanup code needs additional knowledge about the script's state, you can add one or more instance variables to your script class and set them in the ``run`` method.

other methods
-------------

You may define other methods as well, but be careful not to shadow `BaseScript` methods.

.. _lsst.ts.salobj_python_unit_test:

Python Unit Test
================

See ``tests/auxtel/test_slew_telescope_icrs.py`` in the ``ts_standardscripts`` package for an example.

There are two basic parts to testing a script: testing configuration and testing the run method.

Testing configuration is straightforward:

* Write a test method that calls ``configure`` with different sorts of invalid data and make sure that ``configure`` raises a suitable exception.
* Write one or more test methods that calls ``configure`` with valid data and test that your script is now properly configured.

Testing the run method is more work. My suggestion:

* Make a trivial class for each controller that your script commands.
  The class should execute a callback for each commands your script sends.
  Each callback should record any command data you want to check later, and output any events and telemetry that your script relies on.
* Configure the script by sending it the ``do_configure`` command.
  This is important because it puts the script into the `lsst.ts.idl.enums.Script.ScriptState.CONFIGURED` state.
* Run the script by sending it the ``do_run`` command.
* Check that the final state is `lsst.ts.idl.enums.Script.ScriptState.DONE`.
* Check recorded data to see that it matches your expectations.
