.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj-salobj_cscs:

###########
salobj CSCs
###########

-------------
Writing a CSC
-------------
.. _lsst.ts.salobj-writing_a_csc:

* Make your CSC a subclass of `ConfigurableCsc` if it can be configured via the ``start`` command, or `BaseCsc` if not.
* Override `BaseCsc.close_tasks` if you have background tasks to clean up when quitting.
* Handling commands:

    * Your subclass must provide a ``do_<name>`` method for every command
      that is not part of the standard CSC command set, as well as the
      following optional standard commands, if you want to support them:
      ``abort``, ``enterControl``, and ``setValue``.
      `BaseCsc` implements the standard state transition commands.
    * Each ``do_<name>`` method can be synchronous (``def do_<name>...``)
      or asynchronous (``async def do_<name>...``). If ``do_<name>``
      is asynchronous then the command is automatically acknowledged
      as in progress before the callback starts.
    * If a ``do_<name>`` method must perform slow synchronous operations,
      such as CPU-heavy tasks, make the method asynchronous
      and call the synchronous operation in a thread using
      the ``run_in_executor`` method of the event loop.
    * Your CSC reports the command as unsuccessful if the ``do_<name>`` method raises an exception.
      The ``ack`` value depends on the exception; see `ControllerCommand` for details.
    * Your CSC reports the command as successful when ``do_<name>`` finishes and returns `None`.
      If ``do_<name>`` returns an acknowledgement (instance of `SalInfo.AckType`) instead of `None`
      then your CSC sends that as the final command acknowledgement.
    * If you want to allow more than one instance of the command running
      at a time, set ``self.cmd_<name>.allow_multiple_commands = True``
      in your CSC's constructor. See `topics.ControllerCommand`.allow_multiple_commands
      for details and limitations of this attribute.
    * ``do_`` is a reserved prefix: all ``do_<name>`` attributes must match a command name and must be callable.

* Configurable CSCs (subclasses of `ConfigurableCsc`) must provide the following:

    * A ``schema`` that defines the configuration and (if practical) provides a default value for each parameter.
      If all values have sensible defaults then your CSC can be configured without specifying a configuration file as part of the ``start`` command.
    * A ``configure`` method that accepts configuration as a struct-like object (a `types.SimpleNamespace`).
    * A ``get_config_pkg`` classmethod that returns ``ts_config_...``, the package that contains configuration files for your CSC.
    * In that config package:

        * Add a directory whose name is the SAL component, and a subdirectory inside that whose name is your schema version, for example ``ATDome/v1/``. In that subdirectory add the following:
        * Configuration files, if any.
          Only add configuration files if your CSC's default configuration (as defined by the default values specfied in the schema) is not adequate for normal operation modes.
        * A file ``_labels.yaml`` which contains a mapping of ``label: configuration file name`` for each recommended configuration file.
          If you have no configuration files then leave ``_labels.yaml`` blank (except, preferably, a comment saying there are no configuration files), in order to avoid a warning log message when your CSC is constructed.
    * Add the config package to your eups table as a required dependency in your ``ups/<csc_pkg>.table`` file.

* Talking to other CSCs:

    * Your subclass should construct a `Remote` for any
      remote SAL component it wishes to listen to or command.
      For example: ``self.electrometer1 = salobj.Remote(SALPY_Electrometer, index=1)``.

* Summary state and error code:

    * `BaseCsc` provides a default implementation for all summary state
      transition commands that might suffice. However, it does not yet
      handle configuration. See ``ATDomeTrajectory`` for a CSC
      that handles configuration.
    * Most commands should only be allowed to run when the summary state
      is `State.ENABLED`. To check this, put the following as the first
      line of your ``do_<name>`` method: ``self.assert_enabled()``
    * Your subclass may override ``begin_<name>`` and/or ``end_<name>``
      for each state transition command, as appropriate. For complex state
      transitions your subclass may also override ``do_<name>``.
      If any of these methods fail then the state change operation
      is aborted, the summary state does not change, and the command
      is acknowledged as failed.
    * Your subclass may override `BaseCsc.report_summary_state`
      if you wish to perform actions based the current summary state.
      This is an excellent place to :ref:`start and stop a telemetry loop<lsst.ts.salobj-telemetry_loop_example>`.
    * Output the ``errorCode`` event when your CSC goes into the
      `State.FAULT` summary state.

* Detailed state (optional):

    * The ``detailedState`` event is unique to each CSC.
    * ``detailedState`` is optional, but strongly recommended for
      CSCs that are complex enough to have interesting internal state.
    * Report all information that seem relevant to detailed state
      and is not covered by summary state.
    * Detailed state should be *orthogonal* to summary state.
      You may provide an enum field in your detailedState event, but it
      is not required and, if present, should not include summary states.

* Simulation mode (optional):

    * Implement :ref:`simulation mode<lsst.ts.salobj-simulation_mode>`, if practical.
      This allows testing without putting hardware at risk.
      If your CSC talks to hardware then this is especially important.

----------------------------------
Standard State Transition Commands
----------------------------------

Standard CSC commands and their associated summary state changes:

* ``enterControl``: `State.OFFLINE` to `State.STANDBY`.
  This command is only relevant to :ref:`externally commandable CSCs<lsst.ts.salobj-externally_commandable_csc>`.
* ``start``: `State.STANDBY` to `State.DISABLED`
* ``enable``: `State.DISABLED` to `State.ENABLED`

* ``disable``: `State.ENABLED` to `State.DISABLED`
* ``exitControl``: `State.STANDBY` to `State.OFFLINE`.
  An :ref:`externally commandable CSCs<lsst.ts.salobj-externally_commandable_csc>` will keep running; all others will quit after reporting `State.OFFLINE`.
* ``standby``: `State.DISABLED` or `State.FAULT` to `State.STANDBY`

.. _lsst.ts.salobj-externally_commandable_csc:

---------------------------
Externally Commandable CSCs
---------------------------

Externally commandable CSCs are CSC that can be controlled by some means other than SAL when in the `State.OFFLINE` state.
The camera is one example of an externally commandable CSC.

`BaseCsc` and `ConfigurableCsc` are not externally commandable.
They do not support the ``enterControl`` command and they quit in response to the ``exitControl`` command.

To write write an externally commandable CSC using ``lsst.ts.salobj`` do the following in your subclass of `BaseCsc` or `ConfigurableCsc`:

* Override ``do_exitControl`` to not quit.
* Add method ``do_enterControl`` and make it transition from `State.OFFLINE` to `State.STANDBY`
* Add code for external control; this should only work in `State.OFFLINE` state.

.. _lsst.ts.salobj-running_a_csc:

-------------
Running a CSC
-------------

To run your CSC call `asyncio.run` on the `amain` class method.
For example:

  .. code-block:: python

    import asyncio

    from lsst.ts.salobj import TestCsc

    asyncio.run(TestCsc.amain(index=True))

If you wish to provide additional command line arguments for your CSC then you may
override the `BaseCsc.add_arguments` and `BaseCsc.add_kwargs_from_args` class methods.

To run a CSC in a unit test there are two basic approaches: treat CSC as an asynchronous context manager
or construct the CSC and explicitly await its start_task.
The same choices exist for constructing a `Remote`.

Here is an example using an async context manager:

  .. code-block:: python

    index_gen = salobj.index_generator()

    class MyTestCase(asynctest.TestCase)
        def setUp(self):
            salobj.set_random_lsst_dds_domain()

        async def test_something(self):
            index = next(index_gen)
            async with TestCsc(index=index,
                initial_summary_state=salobj.State.ENABLED) as csc, \
                    async with salobj.Remote(domain=csc.domain,
                                             name="Test", index=index) as remote:
                # The csc and remote are ready; add your test code here...

Explicitly waiting is harder to do correctly, since you should call ``close`` on your CSC even if a test fails.
One technique I recommend is to make a "harness" class that is itself an asynchronous context manager
that manages the CSC and `Remote` and possibly other related instances.
This is useful if you are writing multiple tests that need these objects,
especially if the different tests require different configurations.
(If all tests use the same configuration, then you can use build and await
the objects in ``async def setUp`` and close them in ``async def tearDown``).
Here is an example:

  .. code-block:: python

    index_gen = salobj.index_generator()

    class Harness:
        def __init__(self, initial_state, config_dir=None):
            index = next(index_gen)
            self.csc = TestCsc(index=index, initial_state=initial_state)
            self.remote = salobj.Remote(domain=self.csc.domain,
                                        name="Test", index=index)

        async def __aenter__(self):
            await self.csc.start_task
            await self.remote.start_task
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await self.remote.close()
            await self.csc.close()


    class MyTestCase(asynctest.TestCase)
        def setUp(self):
            salobj.set_random_lsst_dds_domain()

        async def test_something(self):
            async with Harness(initial_state=salobj.State.ENABLED) as harness:
                # harness.csc and harness.remote are ready; add your test code here...


.. _lsst.ts.salobj-simulation_mode:

---------------
Simulation Mode
---------------

CSCs should support a simulation mode if practical; this is especially important if the CSC talks to hardware.

To implement a simulation mode, first pick one or more non-zero values
for the ``simulation_mode`` property (0 is reserved for normal operation)
and document what they mean. For example you might use a a bit mask
to supporting independently simulating multiple different subsystems.

Then override `implement_simulation_mode` to implement the specified
simulation mode, if supported, or raise an exception if not.
Note that this method is called during construction of the CSC.
The default implementation of `implement_simulation_mode` is to reject
all non-zero values for ``simulation_mode``.

.. _lsst.ts.salobj-telemetry_loop_example:

----------------------
Telemetry Loop Example
----------------------

Here is an example of how to write a telemetry loop.

1. In the constructor (``__init__``): initialize:

  .. code-block:: python

    self.telemetry_loop_task = salobj.make_done_future()
    self.telemetry_interval = 1  # seconds between telemetry output

  Initializing ``telemetry_loop_task`` to an `asyncio.Future` that is already done makes it easier to test and cancel than initializing it to `None`.

2. Define a ``telemetry_loop`` method, such as:

  .. code-block:: python

    async def telemetry_loop(self):
        while True:
            #...read and write telemetry...
            await asyncio.sleep(self.telemetry_interval)

3. Start and stop the telemetry loop in `BaseCsc.report_summary_state`:

  .. code-block:: python

    def report_summary_state(self):
        super().report_summary_state()
        if self.summary_state in (salobj.State.DISABLED, salobj.State.ENABLED):
            if self.telemetry_loop_task.done():
                self.telemetry_loop_task = asyncio.create_task(self.telemetry_loop())
        else:
            self.telemetry_loop_task.cancel()

4. Finally, cancel any tasks you start in `BaseCsc.close_tasks`.
   This is not strictly needed if you cancel your tasks in ``report_summary_state`` when exiting, but it allows you to close CSCs in the ENABLED or DISABLED state in unit tests without generating annoying warnings about pending tasks.

  .. code-block:: python

    async def close_tasks(self):
        await super().close_tasks()
        self.telemetry_loop_task.cancel()
