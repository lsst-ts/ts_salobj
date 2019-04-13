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
    * Your CSC will report the command as failed if the ``do_<name>``
      method raises an exception. The ``result`` field of that
      acknowledgement will be the data in the exception.
      Eventually the CSC may log a traceback, as well,
      but never for `ExpectedError`.
    * By default your CSC will report the command as completed
      when ``do_<name>`` finishes, but you can return a different
      acknowledgement (instance of `SalInfo.AckType`) instead,
      and that will be used as the final command acknowledgement.
    * If you want to allow more than one instance of the command running
      at a time, set ``self.cmd_<name>.allow_multiple_commands = True``
      in your CSC's constructor. See
      `topics.ControllerCommand`.allow_multiple_commands
      for details and limitations of this attribute.
    * ``do_`` is a reserved prefix: all ``do_<name>`` attributes must match a command name and must be callable.

* Configurable CSCs (subclasses of `ConfigurableCsc`) must provide the following:

    * A ``schema`` that defines the configuration and (if practical) provides a default value for each parameter.
      If all values have sensible defaults then your CSC can be configured without specifying a configuration file as part of the ``start`` command.
    * A ``configure`` method that accepts configuration as a struct-like object (a `types.SimpleNamespace`).
    * A ``get_config_pkg`` classmethod that returns ``ts_config_...``, the package that contains configuration files for your CSC.
    * In that config package add a subdirectory with the name of the SAL component your CSC uses, e.g. ``ATDome``.
    * In that config package subdirectory add a file ``_labels.yaml`` which contains a mapping of label: config file for each recommended config file.
      If you have no such config files then leave ``_labels.yaml`` blank (except, preferably, for a comment), in order to avoid a warning log message when your CSC is constructed.
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
    * Your subclass may override `BaseCsc.report_summary_state` if you wish to
      perform actions based the current summary state.
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

To run your CSC call the `main` method or equivalent code.
For an example see ``bin.src/run_test_csc.py``.
If you wish to provide additional command line arguments for your CSC then you may
override the `BaseCsc.add_arguments` and `BaseCsc.add_kwargs_from_args` class methods,
or, if you prefer, copy the contents of `main` into your ``bin.src`` script
and adapt it as required.

In unit tests, wait for ``self.start_task`` to be done, or for the initial
``summaryState`` event, before expecting the CSC to be responsive.

.. _lsst.ts.salobj-simulation_mode:

---------------
Simulation Mode
---------------

CSCs should support a simulation mode if practical; this is especially
important if the CSC talks to hardware.

To implement a simulation mode, first pick one or more non-zero values
for the ``simulation_mode`` property (0 is reserved for normal operation)
and document what they mean. For example you might use a a bit mask
to supporting independently simulating multiple different subsystems.

Then override `implement_simulation_mode` to implement the specified
simulation mode, if supported, or raise an exception if not.
Note that this method is called during construction of the CSC.
The default implementation of `implement_simulation_mode` is to reject
all non-zero values for ``simulation_mode``.
