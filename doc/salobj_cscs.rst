.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj-salobj_cscs:

###########
salobj CSCs
###########

-------------
Writing a CSC
-------------
.. _lsst.ts.salobj-writing_a_csc:

A Commandable SAL Component (CSC) typically consists of one or more of the following components:

The CSC
^^^^^^^
The CSC responds to commands and outputs events and telemetry.
Make it a subclass of `ConfigurableCsc` if it can be configured via the ``start`` command, or `BaseCsc` if not.
Most CSCs are configurable.

ts_ATDome is one of the simplest CSCs, and makes good example of how to write a CSC.

Connections
^^^^^^^^^^^
If your CSC communicates with a low-level controller then it will need some kind of connection to that controller.
Examples include:

* ts_ATDome, one of the simplest CSCs, communicates to its low-level controller using a single client TCP/IP socket.
* ts_hexapod and ts_rotator communicate to its low-level controller via a pair of TCP/IP client sockets, one for commands and the other for replies.
* ts_MTMount communicates to its low-level controller via a pair of TCP/IP sockets, one a client, one a socket.

If your CSC communicates with other SAL components then it will need one or more `Remote`\ s (one per SAL component).
Examples of CSCs with `Remote`\ s include:

* ts_ATDomeTrajectory has a remote to talk command ATDome and another to listen to ATMCS target event.
  This is one of the simplest CSCs with remotes.
* ts_Watcher uses remotes to listen to the SAL components that it monitors.
* ts_scriptqueue uses a single remote to communicate with all queued scripts.
  This relies on the feature that specifying index=0 allows one to communicate with all indices of an indexed SAL component.

LFA Writer
^^^^^^^^^^
If your CSC writes data to the Large File Annex (or another `S3 <https://docs.aws.amazon.com/s3/index.html>`_ server) then create an `AsyncS3Bucket`, using `AsyncS3Bucket.make_bucket_name` to construct the bucket name.
To upload data:

* Call `AsyncS3Bucket.make_key` to construct a key.
* Call `AsyncS3Bucket.upload` to upload the data (see the doc string for details on getting your data into the required format).
* Fall back to writing your data to local disk if S3 upload fails.
* Call ``evt_largeFileObjectAvailable.set_put`` to report the upload.

See ts_FiberSpectrograph for a simple example.

Note that users of your CSC will have to configure access to the S3 server in the standard way.
Most of such configuration is standard and well documented on the internet.
However, if the S3 server is not part of Amazon Web Services (AWS), you will also have to define salobj-specific environment variable ``S3_ENDPOINT_URL``; see :ref:`lsst.ts.salobj-configuration_environment_variables` for details.

A Model
^^^^^^^
If your CSC has complicated internal state or performs complicated computations then we strongly recommend that you encapsulate that behavior in a class that acts as a data model.
On the other hand, if a low level controller does most of the work then you probably do not need a model.
Examples of CSCs with models include:

* ts_ATDomeTrajectory: the model is the algorithm used to control the dome.
  This is one of the simplest CSCs with a model.
* ts_watcher: the model contains and manages all the rules and alarms.
* ts_scriptqueue: the model contains the queue and information about each script on the queue.

A Simulator
^^^^^^^^^^^
If your CSC controls hardware then we strongly recommend that you support running in simulation mode.
This allows unit testing integration testing of your CSC.

If your CSC talks to a low level controller then consider simulating the low-level controller.
That allows your CSC to use its standard communication protocol to communicate with the simulator, which in turn means that your unit test exercise more of your code.
All the CSCs listed under "Connections" above have a simulator that works this way.

-----------------
Basic Development
-----------------

Read `Developing with the lsstts/develop-env Docker Container <https://confluence.lsstcorp.org/pages/viewpage.action?pageId=107119540>`_ especially "CSC Development".
For detailed advice for configuring your environment see `SAL Development <https://confluence.lsstcorp.org/pages/viewpage.action?pageId=107119540>`_.

Clone the `templates <https://github.com/lsst/templates>`_ package and follow the instructions in its README file to create a new package.

-----------
CSC Details
-----------

Make your CSC a subclass of `ConfigurableCsc` if it can be configured via the ``start`` command, or `BaseCsc` if not.
Most CSCs can be configured.

* Handling commands:

    * Your subclass must provide a ``do_<name>`` method for every command that is not part of the standard CSC command set, as well as the following optional standard commands, if you want to support them (these are rare):

      * ``abort``. Use of this command is discouraged.
        It is usually better to provide CSC-specific commands to stop specific actions.
      * ``enterControl``. This command is only relevant for :ref:`externally commandable CSCs <lsst.ts.salobj-externally_commandable_csc>`.
      * ``setValue``. This is strongly discouraged, for reasons given below.

    * Each ``do_<name>`` method may be synchronous (``def do_<name>...``) or asynchronous (``async def do_<name>...``).
      If ``do_<name>`` is asynchronous then the command is automatically acknowledged as in progress just before ``do_<name>`` method starts.
    * Most commands should only be allowed to run when the summary state is `State.ENABLED`.
      To enforce this, put the following as the first line of your ``do_<name>`` method: ``self.assert_enabled()``
    * Your CSC reports the command as unsuccessful if the ``do_<name>`` method raises an exception.
      The ``ack`` value depends on the exception; see `topics.ControllerCommand` for details.
    * Your CSC reports the command as successful when ``do_<name>`` finishes and returns `None`.
      If ``do_<name>`` returns an acknowledgement (instance of `SalInfo.AckCmdType`) instead of `None`
      then your CSC sends that as the final command acknowledgement.
    * If you want to allow more than one instance of the command running at a time, set ``self.cmd_<name>.allow_multiple_callbacks = True`` in your CSC's constructor.
      See `topics.ReadTopic.allow_multiple_callbacks` for details and limitations of this attribute.
    * If a ``do_<name>`` method must perform slow synchronous operations, such as CPU-heavy tasks or blocking I/O, make the method asynchronous and call the synchronous operation in a thread using the ``run_in_executor`` method of the event loop.
    * ``do_`` is a reserved prefix: all ``do_<name>`` attributes must match a command name and must be callable.
    * It is strongly discouraged to implement the ``setValue`` command or otherwise allow modifying configuration in any way other than the ``start`` command, because that makes it difficult to reproduce the current configuration and determine how it got that way.
      However, if your CSC does allow this, then you are responsible for ouputting the ``appliedSettingsMatchStart`` event with ``appliedSettingsMatchStartIsTrue=False`` when appropriate.

* In your constructor call:

    * ``self.evt_softwareVersions.set(version=...)``; that is ``set`` not ``set_put`` because `BaseCsc` will add more information and then output the event.
      If your CSC has individually versions subsystems then also set the ``subsystemVersions`` field, else leave it blank.
    * If your CSC outputs settings information in events other than ``settingsApplied`` then call:
      ``self.evt_settingsApplied.set(otherSettingsEvents=...)`` with a comma-separated list of the name of those events (without the ``logevent_`` prefix).
    
* Override `BaseCsc.handle_summary_state`  to handle tasks such as:

  * Constructing a model, if your CSC has one.
  * Starting or stopping a telemetry loop and other background tasks.
  * Constructing the simulator, if in simulation mode.
  * Connecting to or disconnecting from a low-level controller (or simulator).

  Here is a typical outline::

    async def handle_summary_state(self):
        if self.disabled_or_enabled:
            if self.model is None:
                self.model = ...
            if self.telemetry_task.done():
                self.telemetry_task = asyncio.create_task(self.telemetry_loop())
            if self.simulation_mode and not self.simulator:
                self.simulator = ...
            if self.connection is None:
                self.connection = ...
        else:
            if self.connection:
                await self.connection.close()
                self.connection = None
            if self.simulator:
                await self.simulator.close()
                self.simulator = None
            self.telemetry_task.cancel()
            if self.model:
                await self.model.close()
                self.model = None

* Override `BaseCsc.close_tasks` if you have background tasks to clean up when quitting.
  This is not strictly needed if you cancel your tasks in `BaseCsc.handle_summary_state`, but it allows you to close CSCs in the ENABLED or DISABLED state in unit tests without generating annoying warnings about pending tasks.

* Configurable CSCs (subclasses of `ConfigurableCsc`) must provide additional `Configurable CSC Details`_.

* Talking to other CSCs:

    * Your subclass should construct a `Remote` for any
      remote SAL component it wishes to listen to or command.
      For example: ``self.electrometer1 = salobj.Remote(SALPY_Electrometer, index=1)``.

* Summary state and error code:

    * `BaseCsc` provides a default implementation for all summary state
      transition commands that might suffice.
    * Most commands should only be allowed to run when the summary state
      is `State.ENABLED`. To check this, put the following as the first
      line of your ``do_<name>`` method: ``self.assert_enabled()``

    * Call `BaseCsc.fault` to send your CSC into the `State.FAULT` summary state.
      Specify the ``code`` and ``report`` arguments so that BaseCsc can output the ``errorCode`` event
      (which should only be output when going to FAULT state).

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

------------------------
Configurable CSC Details
------------------------

Configurable CSCs (subclasses of `ConfigurableCsc`) must provide the following support, in addition to the standard `CSC Details`_:

* A ``schema`` that defines the configuration and, if practical, provides a default value for each parameter.
  If all values have sensible defaults then your CSC can be configured without specifying a configuration file as part of the ``start`` command.
* A ``configure`` method that accepts configuration as a struct-like object (a `types.SimpleNamespace`).
* A ``get_config_pkg`` classmethod that returns ``ts_config_...``, the package that contains configuration files for your CSC.
* In that config package:

    * Add a directory whose name is the SAL component, and a subdirectory inside that whose name is your schema version, for example ``ATDome/v1/``.

      In that subdirectory add the following:

    * Configuration files, if any.
      These are only required if your CSC's default configuration (as defined by the default values specfied in the schema) is not adequate for normal operation modes.
    * A file named ``_labels.yaml`` which contains a mapping of ``label: configuration file name`` for each recommended configuration file.
      If you have no configuration files then leave ``_labels.yaml`` blank (except, preferably, a comment saying there are no configuration files), in order to avoid a warning log message when your CSC is constructed.
    * Add a new test method to the test case in ``tests/test_config_files.py``.
      If your CSC package requires packages that are not part of the ``lsstts/develop-env`` Docker container then use an environment variable to find your package; see ``ts_config_ocs/tests/test_config_files.py`` for a few examples.
    * Run the new unit test, to make sure it works.

* Add the config package to your eups table as a required dependency in your ``ups/<csc_pkg>.table`` file.

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

---------------------
Unit Testing your CSC
---------------------

* Make a unit test case that inherits from `BaseCscTestCase` and `asynctest.TestCase`
* Override the `BaseCscTestCase.basic_make_csc` method to construct and return your CSC.
  You may also construct other objects needed for your tests, with these caveats:

    * `BaseCscTestCase.basic_make_csc` can only return the CSC, so any other objects must be set as instance variables (e.g. ``self.foo = MyFoo(...)``.
    * If any of these objects need to be cleaned up at the end of the test, add a ``tearDown`` method that performs the cleanup.
    * In ``tearDown`` Do not assume that `BaseCscTestCase.basic_make_csc` was called, because some test methods may not need to construct a CSC.
      If you add attributes in `BaseCscTestCase.basic_make_csc` then you must check that they exist in ``tearDown``.
      A simple way to handle this is to add a ``setUp`` method and initialize any such attributes to `None`, then in ``tearDown`` only perform cleanup if the attributes are not ``None``.
* In each test that needs a CSC call ``async with self.make_csc(...):`` to construct:

  * ``self.csc``: the CSC
  * ``self.remote``: a remote that talks to the CSC.
  * Any other objects you construct in ``basic_make_csc``.

See ``tests/test_csc.py`` in this package (ts_salobj) for an example.

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
You will have to do this if your CSC supports simulation mode.
If your CSC only supports simulation on or off (the most common case) then you can write:::

    @classmethod
    def add_arguments(cls, parser):
        super(ATDomeCsc, cls).add_arguments(parser)
        parser.add_argument(
            "-s", "--simulate", action="store_true", help="Run in simuation mode?"
        )

    @classmethod
    def add_kwargs_from_args(cls, args, kwargs):
        super(ATDomeCsc, cls).add_kwargs_from_args(args, kwargs)
        kwargs["simulation_mode"] = 1 if args.simulate else 0

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

--------------------
External Connections
--------------------

If your CSC communicates with some other controller or system (by means other than SAL),
I suggest you make or break the connection in `BaseCsc.handle_summary_state` (or a method called from there) as follows:

* If the current state is DISABLED or ENABLED state and not already connected, then make the connection.
  If you support simulation mode then read that to determine if this is a real or a simulated connection.
* If the current state is something else then disconnect.

Examples include the following (both of which have a simulation mode):

* ts_ATDome talks to a TCP/IP controller
* ts_FiberSpectrograph controls fiber spectrographs over USB.

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

3. Start and stop the telemetry loop in `BaseCsc.handle_summary_state`, as described above.
