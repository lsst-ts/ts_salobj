.. py:currentmodule:: lsst.ts.salobj

.. _lsst.ts.salobj.version_history:

###############
Version History
###############

.. towncrier release notes start

v8.2.3 (2025-06-18)
===================

New Features
------------

- Added schema checking script (`DM-50528 <https://rubinobs.atlassian.net//browse/DM-50528>`_)
- Add new delete_topics submodule with utilities to delete topics and schema from the Kafka broker. (`OSW-397 <https://rubinobs.atlassian.net//browse/OSW-397>`_)


Bug Fixes
---------

- Updated schema deletion operation in ``BaseCscTestCase`` to mark schemas for deletion before permanently deleting them. (`OSW-397 <https://rubinobs.atlassian.net//browse/OSW-397>`_)


Other Changes and Additions
---------------------------

- Updated broker client configuration to remove deprecated request for api version. (`OSW-397 <https://rubinobs.atlassian.net//browse/OSW-397>`_)
- Updated the ``BaseCscTestCase.asyncTearDown`` method to use the new ``DeleteTopics`` class to handle topic deletion. (`OSW-397 <https://rubinobs.atlassian.net//browse/OSW-397>`_)
- Improved handling of exception when deleting consumer group in ``SalInfo``. (`OSW-397 <https://rubinobs.atlassian.net//browse/OSW-397>`_)


v8.2.2 (2025-04-23)
===================

Bug Fixes
---------

- Added the authlib dependency. (`DM-50407 <https://rubinobs.atlassian.net//browse/DM-50407>`_)


v8.2.1 (2025-04-01)
===================

Other Changes and Additions
---------------------------

- Updates conda recipe to replace xml_conda_version with xml_version. (`DM-49653 <https://rubinobs.atlassian.net//browse/DM-49653>`_)


v8.2.0 (2025-04-01)
===================

Other Changes and Additions
---------------------------

- Adds a tearDown method to the BaseCscTescCase class to cleanup the broker after the test is executed. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Improves SalInfo._blocking_create_topics to list the existing topics and only attempt to create the ones that don't exist. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Adds a signal handler for BaseScript to capture SIGINT and SIGTEM and ensure that correct cleanup is executed after receiving a signal. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Make general unit tests improvements. Mostly around cleaning up resources after the unit tests are executed to ensure we are not leaving crud behind in the test kafka cluster. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Adds a signal handler for BaseCSC to capture SIGINT and SIGTEM and ensure that correct cleanup is executed after receiving a signal. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Updates check for duplicate heartbeat, when starting a CSC, to create its own Domain and Remote. This improves resource cleanup, preventing consumers from dangling around. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)
- Updates SalLogHandler to store any message logged before the controller has started and emit them once it is. (`DM-49643 <https://rubinobs.atlassian.net//browse/DM-49643>`_)


v8.1.0
------

Performance Enhancement
-----------------------

- Updated ``SalInfo`` to replace the use of ``Consumer.pool`` with ``Consumer.consume`` and allow users to specify the number of images to consume and the timeout.
  By default, ``num_messages=1`` and ``timeout=0.1``, which falls back to the original behavior with ``Consumer.pool``. (`DM-48885 <https://rubinobs.atlassian.net//browse/DM-48885>`_)
- Updated ``Remote`` to allow users to specify ``num_messages`` and ``consume_messages_timeout``, which is passed on to ``SalInfo`` and used to set how the read loop behaves. (`DM-48885 <https://rubinobs.atlassian.net//browse/DM-48885>`_)

Documentation
-------------

- Replace ``set_random_topic_subname`` references with ``set_test_topic_subname``. (`DM-48919 <https://rubinobs.atlassian.net//browse/DM-48919>`_)


v8.0.0
------

This new major release of salobj replaces DDS with Kafka.

* Update to use Kafka instead of DDS to read and write messages.

* CSCs may specify initial_state=None to use the default state.

* Changes that are most likely to break existing code:

    * `SalInfo`:

        * You must call ``start`` before writing data.
        * Deleted the deprecated ``makeAckCmd`` method; call ``make_ackcmd`` instead.
        * The `SalInfo` ``metadata`` attribute has been replaced by ``component_info``.
          ``component_info`` is more comprehensive (it is used to generate Kafka topics) and is derived directly from the XML files.

    * Messages no longer support the ``get_vars`` method; use the ``vars`` built-in function instead.
      In other words change ``message.get_vars()`` to ``vars(message)``.
    * Deleted function ``get_opensplice_version``.

* Added bin script and entry point ``get_component_info`` to get information about a SAL component from ts_xml.
  The information includes enumerations, Avro schemas for topics, and array lengths for fields.

* `BaseCsc`: stop setting $OSPL_MASTER_PRIORITY; it is not needed for Kafka.
  Delete constant ``MASTER_PRIORITY_ENV_VAR``.

* Move the following submodules to ts_xml:

  * ``component_info.py``
  * ``field_info.py``
  * ``get_component_info.py``
  * ``sal_enums.py``
  * ``get_enums_from_xml.py``
  * ``xml_utils.py``
  * ``type_hints.py``
  * ``topic_info.py``

* Re-export the following submodules to maintain backward compatibility.

    * ``lsst.ts.xml.sal_enums``.
    * ``lsst.ts.xml.type_hints``.

* Remove the do_setAuthList command.

* Give a local variable a more pythonesque name.

v7.8.0
------

* Added optional ``stem`` parameter to ``AsyncS3Bucket::make_key``.
* Implemeted URL return from ``AsyncS3Bucket::upload``.


v7.7.1
------

* Added ``WildcardIndexError`` to handle wildcard indices in SAL components,
  ensuring backward compatibility.


v7.7.0
------

* Add new functionality to allow specifying extra commands for a CSC.
  This will allow us to improve backwards compatibility when adding new commands to CSC.
* Add support for setting block information in BaseScript.


v7.6.1
------

* Remove backward compatibility with moto version 3.
* Remove the do_setAuthList command.
* Give a local variable a more pythonesque name.

v7.6.0
------

* Updated moto to version 5.
* Removed testing for a non-existent warning from a unit test.
* Update the version of the ts-conda-build dependency to 0.4.
* Reformat code with black.

v7.5.0
------

* Removed all references to the `unsigned long` and `unsigned long long` data types, as they are no longer supported.

v7.4.0
------

* CSCs now optionally check for an already-running instance when starting.
  This is always on when starting a CSC using the command line/entry point.
  It is off by default when constructing the CSC class directly, to make unit tests start more quickly.
  To support this:

  * Add optional constructor argument ``check_if_duplicate`` to `BaseCsc`, `ConfigurableCsc`, and `TestCsc`.
  * Add optional argument ``check_if_duplicate`` to `BaseCsc.make_from_cmd_line`.

  Note that existing subclasses need not change anything to get the new behavior.
  You may add optional constructor argument ``check_if_duplicate`` if you like, but it is not very useful.
* Added `topics.MockWriteTopic` and `make_mock_write_topics`.
  These are used to test writers (such as ESS data clients) without actually writing data to SAL.
* `topics.SetWriteResult`: change to a dataclass.
* `topics.WriteTopic`: change ``default_force_output`` from a class variable to an instance variable computed in the constructor.
  This simplifies subclassing and makes `topics.MockWriteTopic` practical.

v7.3.4
------

* `BaseCsc`: fix the log message if an end_<state> method fails; the message claimed it was begin_<state> that failed.
* Add some missing Raises docs, especially missing asyncio.TimeoutError entries.
* `topics.ReadTopic`: eliminate a false warning that async callback functors (classes with async ``__call__`` methods) are synchronous.
* Switched to ts_pre_commit_config.
* ``Jenkinsfile``: use new shared library.
* Remove scons support.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.3.3
------

* `QosSet`: fix doc strings.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.3.2
------

* `CscCommander`:
    * Reduce clutter from logMessage events by only publishing the most interesting fields:
      level, name, message, and (if not empty) traceback.
    * ``telemetry_callback``: do not assume an attribute already exists for previous data.
      This makes it easier to use for events such as clockOffset, where you only want to see the information if it has changed significantly.
      Also improve the documentation.

* Remove some unwanted files that were accidentally added to the last release.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.3.1
------

* `SalLogHandler`: reduce the frequency of "_async_emit' was never awaited" warnings at shutdown.
* ``conda/meta.yaml``: remove redundant "entry_points" information.
* pre-commit: update black to 23.1.0, isort to 5.12.0, mypy to 1.0.0, and pre-commit-hooks to v4.4.0.
* ``Jenkinsfile``: do not run as root.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.3.0
------

* Deprecate synchronous callbacks from ReadTopic, including ``do_x`` methods in CSCs and SAL scripts.
  Also deprecate synchronous ``do_x`` methods in CSC commanders (DM-37501).
* `CscCommander`: add ``telemetry_fields_compare_digits`` constructor argument.
* Improve error output from `BaseConfigTestCase.check_config_files` (DM-37500).

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.2.2
------

* `CscCommander`: remove outdated information from the doc string.
* ``command_test_csc``: call the correct function.
* `TestCscCommander`: remove unused constructor arguments.
* Make mypy 0.991 happy.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.2.1
------

* Modernize the conda recipe.
* Add mypy to pre-commit and update other pre-commit tasks.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.2.0
------

* `BaseScript`: fail with state ``Script.ScriptState.CONFIGURE_FAILED`` if configuration fails.
  This requires ts_idl 4.2.
* `Controller` and `BaseCsc`: add constructor argument ``allow_missing_callbacks``.
  This defaults to false, but if true allows the subclass to omit ``do_{command}`` methods.
  This is useful for writing simple mock CSCs that support a subset of standard behavior.
  Unsupported commands will fail with an appropriate error message.

Requirements:

* ts_ddsconfig
* ts_idl 4.2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.1.4
------

* `ReadTopic`: fix ``aget`` to not steal data from ``next``, as documented.
  This may break existing code that relied on the incorrect behavior, but it makes the queued data more predictable.
* `BaseCscTestCase.make_csc`: eliminate a possible race condition.
* `Remote`:

    * Add missing ``start_called`` method; it was documented but not present.
    * Remote can now be used as an asynchronous context manager, even when constructed with ``start=False``.
    * Add a ``__repr__`` method.

* Fix a few race conditions in unit tests.
* Configure pre-commit to run `isort` to sort imports.
* Modernize type annotations.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.1.3
------

* Correctly process all topics if multiple topics updates are available.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.1.2
------

* Refine `stream_as_generator`:

  * Simplify the code to use loop.run_in_executor instead of being clever.
    (This also makes it compatible with Windows.)
  * Remove the now-unusable `encoding` argument.
  * Add a new `exit_str` argument.

* Fix CI ``Jenkinsfile``: change HOME to WHOME everywhere except final cleanup.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.1.1
------

* Pin the version of moto to be larger than or equal to 3.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.1.0
------

* Update for ts_sal 7, which is required:

  * Remove all references to the "priority" field (RFC-848).
  * Rename "{component_name}ID" fields to "salIndex" (RFC-849).

* `BaseCsc`: make ``start`` easier to use by making the handling of the initial state occur after ``start`` is done (using the new ``start_phase2`` `Controller` method).
  This allows CSCs to write SAL messages in ``start``, after calling ``await super().start()``, without worrying that transitioning to a non-default initial state writes contradictory information.
* `ConfigurableCsc`: always publish the configurationApplied event when transitioning from STANDBY to DISABLED state.
* `Controller`:

    * Add ``write_only`` constructor argument.
    * Add ``start_phase2`` method.

* `BaseScript`:

    * Replace optional ``descr`` argument with ``**kwargs`` in the ``amain`` and ``make_from_cmd_line`` class methods.
      This allows one to define a generic script class that can be used without subclassing, as long as the specifics can be defined by constructor arguments.
      An example is a script that can control the main or auxiliary telescope scheduler, with a constructor argument that specifies which one to control.

    * Simplify error handling in `BaseScript.amain`.
      Only return exit codes 0 (success) or 1.

* `SalInfo`:

    * Add ``write_only`` constructor argument.
    * Log whether authorization support is enabled at INFO level, instead of DEBUG level.

* `SalLogHandler`: support logging from threads.
* Modernize continuous integration ``Jenkinsfile``.
* Start using pyproject.toml.
* Use entry_points instead of bin scripts.
* Unpin the numpy version to be able to build with Python 3.10.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11 using ts_sal 7

v7.0.1
------

* Fix some doc strings.
* `topics.RemoteCommand.start`: improve an error message.
* ``doc/conf.py``: make linters happier.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11

v7.0.0
------

* Update the way configuration is handled to handle our new standard.

    * Write ``configurationApplied`` and ``configurationsAvailable`` events, instead of the obsolete ``settingsApplied`` and ``settingVersions``.
    * Stop writing the obsolete ``appliedSettingsMatchStart`` event.
    * Rename ``start`` command ``settingsToApply`` field to ``configurationOverride``.
    * Rename ``settings_to_apply`` arguments to ``override``.
    * Rename the ``--settings`` CSC command-line argument to ``--override``.
    * Ignore the ``require_settings`` CSC class constant.
      The new configuration system makes default configuration site-specific, and the default is usually fine.

* Warning: `ConfigurableCsc` now requires that environment variable ``LSST_SITE`` be defined.
  As a result:

    * `BaseCscTestCse`: set environment variable ``LSST_SITE`` in ``setUp`` and restore it in ``tearDown``.
      Subclasses with ``setUp`` and/or ``tearDown`` methods should call ``super().setUp()`` and/or ``super().tearDown()``.
    * If you have unit tests that do not inherit from `BaseCscTestCase` and construct a configurable CSC, you will have to manage the environment variable yourself.

* Breaking Changes:

  * Eliminate `BaseCsc.report_summary_state`.
    Use ``handle_summary_state`` instead.
  * Make `BaseCsc.fault` async.
  * Make `BaseScript.set_state` async.
  * Make `Controller.put_log_level` async.
  * Change `topics.CommandEvent`, `topics.CommandTelemetry` and `topics.WriteTopic` ``put`` and ``set_put`` to asynchronous `write` and `set_write`.
    ``write`` does not support writing a data instance; call ``set`` or ``set_write`` to set data.
  * Make `topics.ControllerCommand.ack` and ``ack_in_progress`` async and delete deprecated ``ackInProgress``.
  * `TestCsc`: eliminate the topic-type-specific ``make_random_[cmd/evt/tel]_[arrays/scalars]`` methods.
    Use the new ``make_random_[arrays/scalars]_dict`` methods, instead.
  * Delete ``assert_black_formatted`` and ``tests/test_black.py``; use pytest-black instead.
  * `IdlMetadata`: eliminate the ``str_length`` field (RFC-827).
  * Simplify construction of `topics.BaseTopic`, `topics.ReadTopic`, and `topics.WriteTopic`: use constructor argument ``attr_name`` instead of ``name`` and ``sal_prefix``.
  * `BaseConfigTestCase`: delete the ``get_module_dir`` method.
    It is no longer useful and was unsafe.

* Eliminate the following deprecated features:

    * Configuration schema must be defined in code; salobj will no longer read it from a file:

        * `ConfigurableCsc`: eliminate the deprecated ``schema_path`` constructor argument.
        * Update `check_standard_config_files` to require that the config schema be a module constant.

    * `BaseCsc`: class variable ``valid_simulation_modes`` may no longer be None and class variable ``version`` is required.
    * `CscCommander`: ``get_rounded_public_fields`` is gone; use ``get_rounded_public_data`` with the same arguments.
    * `Remote`: the ``tel_max_history`` constructor argument is gone.
    * `SalInfo`:

        * The ``makeAckCmd`` method is gone; use ``make_ackcmd``.
        * The ``truncate_result`` argument of ``make_ackcmd`` and the ``MAX_RESULT_LEN`` constant are gone.
          Don't worry about length limits.

    * `topics.ReadTopic.get`: eliminate the ``flush`` argument.
    * `topics.RemoteTelemetry`: the constructor no longer accepts the ``max_history`` argument.
    * Delete constants ``MJD_MINUS_UNIX_SECONDS`` and ``SECONDS_PER_DAY`` (use the values in ts_utils).
    * Delete functions (use the same-named version in ts_utils, unless otherwise noted):

        * ``angle_diff``
        * ``angle_wrap_center``
        * ``angle_wrap_nonnegative``
        * ``assertAnglesAlmostEqual``: use ts_utils ``assert_angles_almost_equal``
        * ``astropy_time_from_tai_unix``
        * ``current_tai``
        * ``index_generator``
        * ``make_done_future``
        * ``modify_environ``
        * ``set_random_lsst_dds_domain``: use ``set_random_lsst_dds_partition_prefix``
        * ``tai_from_utc_unix``
        * ``tai_from_utc``
        * ``utc_from_tai_unix``

* Other changes:

    * Stop acknowledging SAL commands with ``CMD_ACK`` (RFC-831).
    * Enhance `CscCommander.make_from_cmd_line` to support index = an IntEnum subclass.
    * Fix the OpenSplice version reported in the ``softwareVersions`` event.
      Report the value of environment variable ``OSPL_RELEASE`` instead of the version of the ``dds`` library.
    * Update ``Jenkinsfile`` to checkout ``ts_config_ocs``.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* IDL files for Test and Script generated from ts_xml 11

v6.9.3
------

* Updated the version of astropy.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* ts_xml 10.1
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.9.2
------

* Change `set_random_lsst_dds_partition_prefix` to use ``os.urandom``, which cannot be seeded, and to generate shorter strings.
* Fix a few places where ts_salobj's deprecated index_generator was still in use, instead of the version in ts_utils.
* `BaseCscTestCase`: add a ``setUp`` method that calls `set_random_lsst_dds_partition_prefix`.
  Retain the existing calls for backwards compatibility with subclasses that define ``setUp`` and don't call ``super().setUp()``.
* `SalInfo`: make ``start`` raise an exception if the instance is already closing or closed.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* ts_xml 10.1
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.9.1
------

* Move index_generator to ts_utils.
  Keep a deprecated copy in ts_salobj, for backwards compatiblity.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1.1
* ts_xml 10.1
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.9.0
------
* Use the new `parse_idl_file` and `make_dds_topic_class` functions in ADLink's ``ddsutil.py``, instead of our versions.
  This change requires ts-dds version 6.9 (community) or 6.10 (licensed) build 18.
* Remove deprecated support for environment variable ``LSST_DDS_DOMAIN``.
* `Remote` and `SalInfo`: improve retrieval of historical data in one special case:
  reading an indexed SAL component using index=0 in the `Remote` (meaning "read data from all indices").
  Formerly there would be only 1 sample of historical data: the most recent sample output with any index.
  Now retrieve the most recent sample *for each index*, in the order received.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 10.1
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.8.1
------

Changes:

* ``test_dds_utils.py``: fix ``test_dds_get_version`` to handle the case that the ``dds`` module has a ``__version__`` attribute.
  This makes the test compatible with OpenSplice 6.11, while retaining compatibility with 6.10.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.8.0
------

Changes:

* `BaseCsc`: output errorCode(errorCode=0, errorReport="", traceback="") when going to any non-fault state.
   Also log a critical error message when going to fault state.
   **Warning:** This change will break unit tests that read errorCode events.
* `CscCommander`: update documentation to expect no extra, unwanted generic commands.
  This reflects what you get with ts_xml 10 and ts_sal 6.
* Fix a new mypy error by not checking DM's `lsst/__init__.py` files.
* Remove all use of SALPY.
  Inter-language SAL communication is now tested in a separate integration test package.
* Update schema links to point to main instead of master.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.7.0
------

Changes:

* Support optional authlist-based command authorization using environment variable ``LSST_DDS_ENABLE_AUTHLIST``.
* Modernize unit tests to use bare `assert`.
* `BaseScript`: support new checkpoint counting fields in Script SAL topics:
  ``totalCheckpoints`` in the ``metadata`` event and ``numCheckpoints`` in the ``state`` event.
* Update ``sal_scripts.rst`` to describe the `BaseScript.set_metadata` method.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 10.1
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.6.4
------

Changes:

* Speed up creation of topics, and thus of controllers, CSCs, scripts and remotes.
  This uses new functions `parse_idl_file` and `make_dds_topic_class`.
  Used together, these are dramatically faster than ``ddsutil.get_dds_classes_from_idl``, because they only parse the IDL file once.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.6.3
------

Changes:

* `BaseCsc.start`: if starting in a state other than the default state,
  add a brief delay after each state transition command.
  This assures that each summaryState event will have a unique value of private_sndStamp,
  avoiding a source of lost summaryState data in the EFD.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.6.2
------

Changes:

* `SalInfo`: if the ``index`` constructor argument is an `enum.IntEnum` then save the value as is.
  Formerly the value was cast to an `int`, which lost information.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.6.1
------

Changes:

* Eliminate some deprecation warnings by using ts_utils functions in all library code.
  I missed some usage of deprecated wrappers for make_done_future and various time functions in v6.6.0.
* Add missing instances of `with self.assertWarns` in unit tests that call deprecated wrapper functions.
* `astropy_time_from_tai_unix`: added a missing deprecation warning and changed it to call the version in ts_utils.
* Fix a "test_none_valid_simulation_modes_simulation_mode" warning in a unit test.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.6.0
------

Changes:

* Moved basic functions to ts_utils, to make them available with fewer dependencies:

  * ``current_tai`` and similar time functions.
  * ``angle_wrap_center`` and similar angle functions.
  * ``make_done_future``.
  * test utilities ``assertAnglesAlmostEqual`` (called ``assert_angles_almost_equal`` in ts_utils) and ``modify_environ``.

* Added temporary wrappers for the code that was moved, for backwards compatibility.
  These wrappers issue a `DepreciationWarning` warning and will be removed in ts_salobj v7.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_utils 1
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.5
------

Changes:

* In `BaseCscTestCase.make_csc` Stop adding `StreamHandler` to the loggers.
  If debugging unit tests use `--log-cli-level` to show log messages.
* Fix `tests/test_speed.py` for when `lsst.verify` cannot be imported (needed for conda packages).

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.4
------

Changes:

* Expanded mypy test coverage by enabling ``disallow_untyped_defs``.
  Fixed the resulting type errors.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.3
------

Changes:

* Change `set_random_lsst_dds_partition_prefix` to not use "." in the name,
  in order to work around a bug in OpenSplice 6.11.1.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.2
------

Changes:

* Stop using deprecated ``char`` and ``octet`` fields in the Test SAL component.
  They are ignored if present, for backwards compatibility.
* Updated the two included IDL files to remove the ``char`` and ``octet`` fields
  and updated the data to match that generated by ts_sal 6 pre-release (no significant changes).
* `parse_idl` bug fix: if the units was missing then it could not find the description.
  The only such field is the index field for indexed SAL components (e.g. ``TestID``).

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.1
------

Changes:

* Prevent pytest from checking the generated ``version.py`` file.
  This is necessary in order to prevent ``mypy`` from checking that file.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.5.0
------

Changes:

* Add type annotations and check them with mypy.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.4.3
------

Changes:

* `topics.WriteTopic.set`: make NaNs compare equal when deciding if the data has changed.
  As a result, `topics.ControllerEvent.set_put` will no longer output a new event
  if the only change is to set NaN values to NaN again.
* `TestCsc` assert_arrays/scalars_equal methods: make NaNs compare equal.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.4.2
------

Changes:

* Bug fix: test_idl_parser was still expecting the private_host field to be present.
  It is now optional.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.4.1
------

Changes:

* Pin the versions of astropy and numpy.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.4.0
------

Changes:

* Added function `utc_from_tai_unix`.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.3.8
------

Changes:

* Make tests/test_salobj_to_either.py compatible with ts_sal 6.
* `DefaultingValidator`: document that defaults are only handled 2 levels deep.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5 or 6

v6.3.7
------

Changes:

* `CscCommander`: remove the ability to mark trailing comments with ``#``.
* `CscCommander`: add the ability to quote parameters, allowing them to contain spaces.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.6
------

Changes:

* `BaseScript` and `ConfigurableCsc`: ignore a ``metadata`` dict entry, if present, in config files.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.5
------

Changes:

* `CscCommander`: handle bool command arguments correctly.
  Allow any of 0, 1, f, t, false, true (case blind).
* Rewrite the configuration documentation to reduce duplication with the documentation for ts_ddsconfig.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.4
------

Changes:

* Improve handling of errors in the constructor in `SalInfo`, `Controller`, `BaseCsc` and `BaseScript`:
  Make sure the close methods will not access missing attributes.
* `BaseCsc`: check the simulation mode before calling the parent class's constructor, to avoid needlessly constructing a `Domain`.
* `BaseCsc`: remove internal variable ``_requested_summary_state``.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.3
------

Changes:

* Format the code using black 20.8b1.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.2
------

Changes:

* Use ``import unittest.mock`` instead of ``import unittest`` when using mocks.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.1
------

Changes:

* `BaseCscTestCase`: add ``timeout`` argument to ``check_bin_script``.
* Stop using the abandoned ``asynctest`` library.
* Update test function `modify_environ` to use `unittest.mock.patch` and use it in all tests
  that modify os.environ (except we still don't reset env var ``LSST_DDS_PARTITION_PREFIX``
  after calling `set_random_lsst_dds_partition_prefix`, which is a potential issue).
* `SalInfo`: remove read conditions from the contained dds WaitSet when closing.
  ADLink suggested doing this (in my case 00020504) to avoid spurious error messages at shutdown.
* `topics.RemoteCommand`: fix a documentation error and improve the documentation
  for the ``wait_done`` argument to the ``start``, ``set_start``, and ``next_ackcmd`` methods.
* `BaseCsc` and `CscCommander`: improve the documentation
  for the ``index`` argument to the ``amain`` and ``make_from_cmd_line`` class methods.
* `Controller`: stop ignoring optional extra commands.
  ts_xml must now specify the correct commands for each SAL component.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.3.0
------

Deprecations:

* Deprecate `BaseCsc.set_simulation_mode`. Note that `BaseCsc.implement_simulation_mode`,
  and allowing ``valid_simulation_modes = None`` have both been deprecated for some time.
  Please move all simulation mode handling to the constructor (if synchronous) or `BaseCsc.start` (if not).
* Deprecate omitting the ``version`` class attribute of CSCs.
* Deprecate `ConfigurableCsc` constructor argument ``schema_path``; please specify ``config_schema`` instead.

Changes:

* `BaseCsc`: support better help for the ``--simulate`` command-line argument,
  via a new ``simulation_help`` class variable which defaults to `None`.
  If not `None` and the CSC supports simulation, use this variable as the help string
  for the ``--simulate`` command-line argument.
* `BaseCsc`: set the simulation mode attribute in the constructor,
  instead of waiting until partway through the ``start`` method.
  Warning: if ``valid_simulation_modes`` is None then we cannot check it first, but should be checked later.
* `BaseCsc`: if there is no ``version`` attribute,
  set the ``cscVersions`` field of the ``softwareVersions`` event to "?",
  instead of "" (that was a bug), and issue a deprecation warning.
* `ConfigurableCsc`: add constructor argument ``config_schema``.
  this is the preferred way to specify the configuration schema because it allows the schema to be code,
  which simplifies packaging and distribution.
* `BaseConfigTestCase`: added argument ``schema_name`` to ``check_standard_config_files``
  and made ``sal_name`` optional.
* Update test for warnings to include testing for the correct message.
  This makes sure the correct warning is seen (or not seen).

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.2.4
------

Changes:

* Remove test_no_commands from test_sal_info.py because ts_xml 8 no longer has a SAL component with no commands.
  This makes ts_salobj compatible with bohth ts_xml 7.1 and 8.
* Update doc/conf.py to work with documenteer 0.6.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test and Script generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.2.3
------

Changes:

* Add ``noarch: generic`` to the ``build`` section of ``conda/meta.yaml``.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.2.2
------

Changes:

* `CscCommander`: add a digits argument to telemetry_callback method.
* Documentation: document that configuration label names must be valid python identifiers,
  and must not begin with ``_`` (underscore).

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.2.1
------

Changes:

* Added context manager `modify_environ` to temporarily modify environment variables in unit tests.
  This is rather heavyweight (it copies `os.environ`), so I don't recommended it for production code.
* `BaseScript`: modified the constructor to restore the original value (or lack of value)
   of environment variable ``OSPL_MASTER_PRIORITY``, after setting it to 0 to build the `Domain`.
* `AsyncS3Bucket`: simplified to not temporarily set environment variables holding ASW S3 secrets in mock mode.
  It turns out the ``moto`` mocking system already does this (and I added a test to verify that).
* `BaseCsc`: improved the output of ``_do_change_state`` to avoid an unnecessary traceback
  if the called code raises `ExpectedError`.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.2.0
------

Deprecations:

* `CscCommander.get_rounded_public_fields` is deprecated. Call `CscCommander.get_rounded_public_data` instead.

Changes:

* Improve `CscCommander`:

    * Add ``exclude_commands`` and ``telemetry_fields_to_not_compare`` constructor arguments.
    * Add method ``format_dict``.
    * Renamed method ``get_rounded_public_fields`` to ``get_rounded_public_data``, for consistency.
      The old method remains, for backwards compatibility, but is deprecated.
    * Round telemetry to 2 digits by default, instead of 4.
      That should greatly reduce the need to write custom code for CSC commanders.

* Improve `Controller` to fail in the constructor if the ``authList`` event is missing.
  The event was already required; this change simply reports the error earlier and more clearly.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.1.2
------

Changes:

* Fixed documented range of values for LSST_DDS_DOMAIN_ID in configuration.
  According to the reply to an ADLink ticket I filed their manual is in error; 0 and 230 are fine.
* Require ts_xml 6.2 or later.
  Removed a small piece of ts_xml 6.1 compatibility code from tests/test_csc_configuration.py.
* Add installation instructions.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.1.1
------

Document updates:

* Document environment variable LSST_DDS_DOMAIN_ID in configuration.
* Fix two incorrect references to AckCmdType.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.2
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5


v6.1.0
------

Backwards-incompatible changes:

    * ``initial-state`` can no longer be `salobj.State.FAULT` when constructing a CSC.
      This may break some unit tests.

Changes:

* Gets its configuration from the new ``ts_ddsconfig`` package.
* Improved support for specifying the initial state of the CSC:

    * Add ``enable_cmdline_state`` class variable, which defaults to False.
      If True then `BaseCsc.amain` adds ``--state`` and (if relevant) ``--settings`` command-line argument`.
    * Added constructor argument ``settings_to_apply`` to `BaseCsc` and `ConfigurableCsc`.
      If you have a configurable CSC then you should add this parameter to your constructor.
    * CSCs now handle ``initial_state`` differently: the CSC starts in the default initial state
      and `BaseCsc.start` transitions to each intermediate state in turn.
    * As a result, ``initial_state`` can no longer be `State.FAULT`.

* Added function `get_expected_summary_states`.
* Improved `BaseCsc.amain` to accept an `enum.IntEnum` as the value of the index parameter.
  This restricts the allowed values and describes each value in the help.
* Improved `BaseCscTestCase.assert_next_sample` to try to cast read SAL values to the apppropriate enum,
  if the expected value is an instance of `enum.IntEnum`.
  This makes errors easier to understand.
* Improved `Controller` startup: commands will be ignored until the `Controller` has (at least mostly) started.
  This avoids mysterious errors from commanding a partially constructed SAL component.
* Improved the output of `BaseCscTestCase` if the subprocess dies.
* Uses ``pre-commit`` instead of a custom git pre-commit hook.
  You may have to do the following to take advantage of it:

    * Run `pre-commit install` once.
    * If directed, run `git config --unset-all core.hooksPath` once.

How to update your Code. Except as noted, all changes are backwards compatible with ts_salobj 6.0:

* If your CSC overrides the `BaseCsc.start` method, make sure it calls ``await super().start()``
  at or near the *end* of your ``start`` method, not the beginning.
  This is because `BaseCsc.start()` can now call state transition commands,
  which will trigger calls to `BaseCsc.handle_summary_state`;
  thus your CSC should be as "started" as practical before calling ``await super().start()``.
* If you wish to be able to specify the initial state of your CSC from the command line:

  * Set class variable ``enable_cmdline_state`` to True.
  * If your CSC is configurable and does not have a usable default configuration
    (so it *must* have settings specified in the ``start`` command)
    specify class variable ``settings_required = True``.
    This is rare, but Watcher is one such CSC.

* If you have a configurable CSC, add constructor argument ``settings_to_apply=""`` and pass it (by name) to ``super().__init__``.
  This is essential if you set ``enable_cmdline_state = True``, and useful for unit tests even if not.
  This change is *not* backwards compatible with ts_salobj 6.0.
* If your CSC is "externally commandable" (it does not quit in OFFLINE state)
  specify class variable ``default_initial_state = salobj.State.OFFLINE``.

Requirements:

* ts_ddsconfig
* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.0.4
------

Changes:

* Fix `SalLogHandler.emit` to handle message and traceback data with unencodable characters,
  and to never raise an exception.
  This fixes `DM-27380 <https://jira.lsstcorp.org/browse/DM-27380>`_
* Beef up the unit test for invalid configuration to make sure the correct exception is raised
  and that the CSC can still be configured.

Requirements:

* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.0.3
------

Changes:

* Fix an entry in ``Writing a CSC`` about setting ``evt_softwareVersions`` and ``evt_settingsApplied``.

Requirements:

* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.0.2
------

Changes:

* Add support for class variable ``version`` to `BaseCsc`:

    * If ``version`` is set, report it in the ``cscVersion`` field of the ``softwareVersions`` event.
    * If ``version`` is set, add a ``--version`` command-line argument to `BaseCsc.amain`
      that prints the version and quits.
      Otherwise do not add that command-line argument.
      Note: formerly the ``--version`` command-line argument was always present, but returned the version of ts_salobj.

* Update "Writing a CSC" documentation accordingly.
* Improved error handling in `BaseCscTestCase.make_csc`.
  Fails gracefully if the CSC or Remote cannot be constructed.
* The deprecated `lsst.ts.salobj.test_utils` submodule is gone; use `lsst.ts.salobj` directly.

Requirements:

* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.0.1
------

Changes:

* Fixed a bug in `assert_black_formatted`: it did not exclude enough files.
  Note: to exclude ``version.py`` you must specify it in ``.gitignore`` as ``version.py``,
  not by its full path (e.g. do not specify ``python/lsst/ts/salobj/version.py``).

Requirements:

* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v6.0.0
------

Backward Incompatible Changes:

* All SAL components on your system must use ts_salobj v6, ts_sal v5, and ts_idl v2.
* All quality of service (QoS) settings are now defined in ts_idl ``idl/QoS.xml``, both for ts_salobj v6 and ts_sal v5.
  Thus QoS changes no longer require any code changes.
  This change requires ts_idl v2.
* This new QoS file has 4 separate profiles for: commands, events, telemetry topics, and the ackcmd topic,
  and, as of this writing, each profile is different.
* Topics use a new DDS partition naming scheme.
* `topics.ReadTopic.get` now defaults to *not* flushing the queue.
  Also specifying the ``flush`` argument is now deprecated; the argument will be removed in a future version of salobj.
* Requires ts_xml 6 and IDL files built with ts_sal 5, for authorization support.
* Commands are no longer acknowledged with ``CMD_INPROGRESS`` if the do_xxx callback function is asynchronous.
  This was needlessly chatty.
  Instead users are expected to issue such an ack manually (e.g. by calling `topics.ControllerCommand.ack_in_progress`)
  when beginning to execute a command that will take significant time before it is reported as ``CMD_COMPLETE``.
* The `force_output` argument to `topics.ControllerEvent.set_put` is now keyword-only.
* Removed constant ``DDS_READ_QUEUE_LEN``.
  It is very unlikely that any code outside of ts_salobj was using this.
* Removed ``bin/purge_topics.py`` command-line script, because it is no longer needed.
* Removed many deprecated features:

    * Removed ``main`` method from `BaseCsc` and `BaseScript`.
      Call `BaseCsc.amain` or `BaseScript.amain` instead, e.g. ``asyncio.run(MyCSC(index=...))`` or ``asyncio.run(MyScript.amain())``.
    * Removed ``initial_simulation_mode`` argument from `BaseCsc` and `ConfigurableCsc`.
      Use ``simulation_mode`` instead.
    * Removed support for calling `BaseCsc.fault` without an error code or report; both must now be specified.
    * Removed support for setting ``BaseCsc.summary_state`` directly.
      To transition your CSC to a FAULT state call the `BaseCsc.fault` method.
      Unit tests may call the `set_summary_state` function or issue the usual state transition commands.
    * Removed the `SalInfo.idl_loc` property; use ``SalInfo.metadata.idl_path`` instead.
    * Removed the `max_history` argument from `topics.ControllerCommand`\ 's constructor.
      Commands are volatile, so historical data is not available.

Deprecations:

* Simplified simulation mode support in CSCs.
  This is described in :ref:`simulation mode<lsst.ts.salobj-simulation_mode>` and results in the following deprecations:

  * CSCs should now set class variable ``valid_simulation_modes``, even if they do not support simulation.
    Failure to do so will result in a deprecation warning, but supports the old way of doing things.
  * Deprecated `BaseCsc.implement_simulation_mode`.
    Start your simulator in whichever other method seems most appropriate.
  * Deprecated the need to override `BaseCsc.add_arguments` and `BaseCsc.add_kwargs_from_args` to add the ``--simulate`` command-line argument.
    This argument is added automatically if ``valid_simulation_modes`` has more than one entry.

* Renamed environment variable ``LSST_DDS_DOMAIN`` to ``LSST_DDS_PARTITION_PREFIX``.
  The old environment variable is used, with a deprecation warning, if the new one is not defined.
* Renamed `SalInfo.makeAckCmd` to `SalInfo.make_ackcmd`.
  The old method is still available, but issues a deprecation warning.
* Renamed `ControllerCommand.ackInProgress` to `ControllerCommand.ack_in_progress` and added a required `timeout` argument.
   The old method is still available, but issues a deprecation warning.
* `Remote`: the ``tel_max_history`` constructor argument is deprecated and should not be specified.
  If specified it must be 0 (or `None`, but please don't do that).
* `topics.RemoteTelemetry`: the ``max_history`` constructor argument is deprecated and should not be specified.
  If specified then it must be 0 (or `None`, but please don't do that).

Changes:

* Implemented authorization support, though that is off by default for now.
  This will not be complete until ts_sal has full support.
* Simplified the simulation support in CSCs, as explained in Deprecations above.
* Added ``--loglevel`` and ``--version`` arguments to `BaseCsc`\ 's command-line argument parser.
* `CscCommander` now rounds float arrays when displaying events and telemetry (it already rounded float scalars).
* `CscCommander` now supports unit testing.
  To better support unit testing, please write output using the new `CscCommander.output` method, instead of `print`.
* Added support for running without a durability service:
  set environment variable ``LSST_DDS_HISTORYSYNC`` to a negative value to prevent waiting for historical data.
* Added the `get_opensplice_version` function.
* If a command is acknowledged with ``CMD_INPROGRESS`` then the command timeout is extended by the ``timeout`` value in the acknowledgement.
  Thus a slow command will need a long timeout as long as command issues a ``CMD_INPROGRESS`` acknowledgement with a reasonable ``timeout`` value.
* Added the ``settingsToApply`` argument to `BaseCscTestCase.check_standard_state_transitions`,
  to allow testing CSCs that do not have a default configuration.
* Environment variable ``LSST_DDS_IP`` is no longer used.
* The ``private_host`` field of DDS topics is no longer read nor set.
* Updated the git pre-commit hook to prevent the commit if black formatting needed.
  This encourages the user to properly commit the necessary reformatting.
* Update ``Jenkinsfile`` to disable concurrent builds and clean up old log files.
* Removed the ``.travis.yml`` file because it duplicates testing done in Jenkins.
* Use `asynco.create_task` instead of deprecated `asyncio.ensure_future`.
* Added property `topics.ReadTopic.nqueued`.
* Fixed a bug in `topics.ReadTopic.aget`: if multiple messages arrived in the DDS queue while waiting, it would return the oldest message, rather than the newest.
* Improved the documentation for `topics.ReadTopic`.
* Read topics now use a named constant ``DEFAULT_QUEUE_LEN`` as the default value for ``queue_len``, making it easy to change in future.
* Modified the way DDS data is read to lower the risk of the DDS read queue filling up.
* Improved cleanup to fix warnings exposed by setting $PYTHONDEVMODE=1.
* Improved ``Jenkinsfile`` to run tests with ``pytest`` instead of ``py.test``.

Requirements:

* ts_idl 2
* ts_xml 6.1 (older versions might work but have not been tested)
* IDL files for Test, Script, and LOVE generated by ts_sal 5
* SALPY_Test generated by ts_sal 5

v5.17.2
------=

Changes:

* Work around a bug in licensed OpenSplice 6.10.4 and 6.10.3 (case 00020647).
  The workaround is compatible with the community edition of OpenSplice 6.9.190705.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.17.1
------=

Changes:

* Bug fix: `BaseCscTestCase.check_bin_script` now sets a random ``LSST_DDS_DOMAIN``, just like ``make_csc``.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.17.0
------=

Changes:

* Added the `CscCommander.start` method and the ``--enable`` command-line flag.
* Added the `SalInfo.name_index` property.
* Made `SalInfo` an async contextual manager. This is primarily useful for unit tests.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.16.0
------=

Changes:

* Add the ``filter_ackcmd`` argument to `ReadTopic`\ 's constructor.
* Improve Jenkins.conda cleanup.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.15.2
------=

Changes:

* Made `RemoteCommand.next` capable of being called by multiple coroutines at the same time.
  This change should also eliminate a source of index errors.
* Bug fix: two tests in ``test_topics.py`` failed if ``LSST_DDS_IP`` was defined.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.15.1
------=

Changes:

* Updated for compatibility with ts_sal 4.2, while retaining compatibility with 4.1
  This required a small change to one unit test.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.15.0
------=

Changes:

* Add `angle_wrap_center` and `angle_wrap_nonnegative` functions.
* Broke the test of black formatting out into its own test file ``test_black.py``,
  to make it easier to copy into other packages.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.14.0
------=

Changes:

* Add ``create`` and ``profile`` arguments to `AsyncS3Bucket`\ 's constructor.
* Add ``other`` and ``suffix`` arguments to `AsyncS3Bucket.make_key`.
* Change `current_tai`, `current_tai_from_utc`, `tai_from_utc`, and `tai_from_utc_unix` to return `float`.
    Formerly they returned a `numpy.float64` scalar (though `current_tai` returned a `float` if using ``CLOCK_TAI``).
* Add ``timeout`` argument to `BaseCscTestCase.make_csc` to handle CSCs that are very slow to start.
* Added minimal compatibility with ts_xml 5.2: the new generic ``setAuthList`` command.
  `Controller` can be constructed, but the command is not yet supported.
* Sped up ``test_csc.py`` by reducing a needlessly long timeout introduced in v5.12.0.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.13.1
------=

Changes:

* Enable test of IDL topic metadata for array fields. This requires IDL files generated by ts_sal 4.1 or later.
* Make some improvements to ``setup.py`` to add requirements.
* Add build/upload pypi package to Jenkinsfile.conda.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE generated by ts_sal 4.1 or later
* SALPY_Test generated by ts_sal 4.1 or later

v5.13.0
------=

Backwards incompatible changes:

* `topics.RemoteCommand.set` and `topics.RemoteCommand.set_start` now start from a fresh data sample,
  rather than using the parameters for the most recent command (``self.data``) as defaults.
  This makes behavior easier to understand and avoids unpleasant surprises.
  It should affect very little code, since most code specifies all parameters for each call.

Other changes:

* `current_tai` now uses the system TAI clock, if available (only on Linux) and if it gives a reasonable time.
  Salobj logs a warning such as ``current_tai uses current_tai_from_utc; clock_gettime(CLOCK_TAI) is off by 37.0 seconds``
  if CLOCK_TAI does not give a reasonable time.
  This warning indicates that salobj is computing TAI from the standard UTC-ish system clock;
  that time will be accurate on most days, but it will be off by up to a second on the day of a leap second.
* `set_summary_state` now accepts ``settingsToApply=None``.
  Formerly it was not supported, but might work.
* Improved IO errors handling while accessing schema, labels and configuration
  file in `ConfigurableCsc`.
* `ConfigurableCsc.get_default_config_dir` renamed to
  `ConfigurableCsc._get_default_config_dir`.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.12.0
------=

Backwards incompatible changes:

* Many methods of topics in `Remote`\ s now raise `RuntimeError` if the remote has not yet started.
  This may cause some code (especially unit tests) to fail with a `RuntimeError`.
  The fix is to make sure the code waits for `Remote.start_task` before trying to read data or issue commands.
  In unit tests consider using ``async with salobj.Remote(...) as remote:``.
  The methods that raise are:

  * Data reading methods: `topics.ReadTopic.has_data`, `topics.ReadTopic.aget`,  `topics.ReadTopic.get`,
    `topics.ReadTopic.get_oldest`, and `topics.ReadTopic.next`.
  * Command issuing methods: `topics.RemoteCommand.start` and `topics.RemoteCommand.set_start`.

Other changes:

* Fixed an error in `name_to_name_index`: it could not handle names that contained integers (DM-24933).
* Fixed an error in `BaseCscTestCase.make_csc`: ``log_level`` was ignored after the first call, and also ignored if the level was greater than (verbosity less than) WARNING.
* Improved `BaseCscTestCase.make_csc` to allow ``log_level=None`` (do not change the log level) and make that the default.
* Update `BaseScript.start` to wait for its remotes to start.
* Update `CscCommander` to include the received time as part of event and telemetry output.
* Improved the error message from `BaseCscTestCase.assert_next_sample` to specify which field failed.
* Improved tests/test_speed.py:

    * Fixed a bug: the measurement "salobj.CreateClasses" was reported as the inverse of the correct value.
    * Do not fail the read speed measurements if samples are lost; writing is faster than reading, so some loss is likely.
      Instead, print the number of samples lost.
    * Improve the measurement "salobj.ReadTest_logLevel" by ignoring an extra logLevel event output by `Controller`.
    * Be more careful about shutting down the topic writer subprocess.
      This eliminates a warning about an unclosed socket.
    * Reduced the number of samples read and written, since it doesn't affect the measurements,
      speeds up the test, and may reduce lost samples.
    * Removed the combined read/write speed test because it is redundant with the tests added in v5.11.0.

* Minor improvements to ``test_salobj_to_either.py`` and ``test_salpy_to_either.py``,
  including printing how long it takes to create the listeneners,
  which is an upper limit (and decent approximation) of how long it waits for historical data.
* Made time limits in unit tests more generous and simpler.
  This should help test robustness on computers that are slow or starved for resources.
* Fixed flake8 warnings about f strings with no {}.
* Removed deprecated ``sudo: false`` entry from ``.travis.yml``, in order to allow github checks to pass once again.
* Modified `assert_black_formatted` to ignore ``version.py``.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.11.0
------=

Major changes:

* Update CscCommander to support custom commands and to run commands in the background.
* Add new speed tests for issuing commands, reading small and large topics, and writing small and large topics.
  Results of the speed tests are uploaded to SQuaSH by Jenkins.
* Add new function `assert_black_formatted` to simplify making sure code remains formatted with ``black``,
  and a unit test that calls the function.
* Increased the shutdown delay in `Controller` from 0.5 seconds to 1 second,
  in order to give `Remote`\ s a bit more time to read final SAL/DDS messages.
  This may require tweaking timeouts in unit tests that wait for a controller to quit.

Other changes:

* Update the CSC documentation to move the details for configurable CSCs to a new section.
* Change `SalInfo` to only set the log level if it is less verbose than `loggint.INFO`.
  That makes it easier to set a more verbose level in unit tests.
* Update a unit test for compatibility with the pending release of ts_xml 5.2.
* Made ``test_salpy_to_either.py`` more robust by increasing the polling rate for messages.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.10.0
------=

Major changes:

* Sped up DDS message read and write by a factor of 8, as reported by ``tests/test_speed.py``.
  This was done by speeding up `tai_from_utc`, which turned out to be the bottleneck.
* Add function `tai_from_utc_unix`, which does most of the work for `tai_from_utc`.

Minor changes:

* Improved the Jenkins file handling for building and uploading the documentation.
  If building the documentation fails then the Jenkins job fails.
  If uploading the documentation fails then the Jenkins job is marked as unstable.

Notes:

* `tai_from_utc` and `astropy_time_from_tai_unix` will be deprecated once we upgrade to a version of AstroPy that supports TAI seconds directly.
  That change has been committed to the AstroPy code base.
  The new function `tai_from_utc_unix` will remain.
* salobj now uses a daemon thread to maintain an internal leap second table.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.9.0
------

Backwards incompatible changes:

* The arguments have changed slightly for `AsyncS3Bucket.make_bucket_name` and `AsyncS3Bucket.make_key` and the returned values are quite different.
  We changed our standards because it turns out that large numbers of buckets are a problem for Amazon Web Services (AWS).

Major changes:

* Add a ``timeout`` argument to `BaseCscTestCase.check_standard_state_transitions`.
* Update `BaseCsc.start` to output the ``softwareVersions`` event.
* Update `ConfigurableCsc` to output the ``settingsApplied`` event.

Minor changes:

* Allow the ``SALPY_Test`` library to be missing: skip the few necessary unit tests if the library is not found.
* The Jenkins job now builds and uploads the documentation (even if unit tests fail).
* Improve the reliability of ``tests/test_salobj_to_either.py`` by increasing a time limit.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.8.0
------

Major changes:

* Improved `AsyncS3Bucket`:

    * Read environment variable ``S3_ENDPOINT_URL`` to obtain the endpoint URL.
      This allows use with non-AWS S3 servers.
    * Added support for running a mock S3 server: a new ``domock`` constructor argument and `AsyncS3Bucket.stop_mock` method.
      This is intended for CSCs running in simulation mode, and for unit tests.
    * Added static method `AsyncS3Bucket.make_bucket_name`.
    * Added static method `AsyncS3Bucket.make_key`.

* Improved `BaseCscTestCase`:

    * Added argument ``skip_commands`` to `BaseCscTestCase.check_standard_state_transitions`.
    * Added argument ``**kwargs`` to `BaseCscTestCase.make_csc` and `BaseCscTestCase.basic_make_csc`.
    * Changed argument ``*cmdline_args`` to ``cmdline_args`` for `BaseCscTestCase.check_bin_script`, for clarity.

Other changes:

* Added a :ref:`lsst.ts.salobj-configuration` section to the documentation.
* Added missing unit test for `topics.QueueCapacityChecker`.
* Standardized the formatting for attributes documented in the Notes section for some classes.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.7.0
------

Major changes:

* Added `astropy_time_from_tai_unix` function.
* Added `CscCommander` to support exercising CSCs from trivial command-line scripts (DM-23771).
* Added ``bin/zrun_test_commander.py`` to exercise `CscCommander`.
* Added `stream_as_generator` to support reading user input from asyncio-based interactive command-line scripts, such as CSC commanders.
* The package is now conda-installable.
* Added constants ``LOCAL_HOST``, ``SECONDS_PER_DAY`` and ``MJD_MINUS_UNIX_SECONDS``.

Other changes:

* Set the ``name`` field of ``logMessage``, if available (DM-23812).
* Fixed two issues in `tai_from_utc` when provided with an `astropy.time.Time`.

    * Using the default value for the ``scale`` argument caused incorrect behavior.
      Now the ``scale`` argument is ignored, as it should be, since astropy time's have their own scale.
    * The behavior on a leap second day was not well documented and differed from `astropy.time`.
      Document it and match `astropy.time`.

* Improved logging for queues filling up, especially the DDS queue (DM-23802).
* Prevent `BaseScript` from being constructed with index=0, because such a script would receive commands for every script (DM-23900).
* Fixed a bug in `ConfigurableCsc.begin_start` that could result in an undefined variable when trying to print an error message.
* Load the astropy leap second table at startup, so the first call to `current_tai` is fast.
* Use `time.monotonic` instead of `time.time` to measure durations.

Requirements:

* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.6.0
------

Major changes:

* Added `BaseConfigTestCase` to support testing configuration files in ts_config_x packages.

Requirements:

* black
* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.5.0
------

Major changes:

* Scripts now launch with master priority 0 (or will, once https://jira.lsstcorp.org/browse/DM-23462 is implemented).
  This should make scripts launch more quickly.

Requirements:

* black
* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.4.0
------

Major changes:

* Add support for the new ``setGroupId`` ``Script``  command to `BaseScript`:

    * Scripts must now have a non-blank group ID before they are run.
    * Add `BaseScript.group_id` property.
    * Add `BaseScript.next_supplemented_group_id` method.
* Changed `BaseScript.do_resume` and `BaseScript.do_setCheckpoints` to asynchronous, so all ``do_...`` methods are asynchronous, for consistency. I did not find any code outside of ts_salobj that was affected, but it is a potentially breaking change.
* Output fields added to the ``logMessage`` event in ts_xml 4.7.
* Code formatted by ``black``, with a pre-commit hook to enforce this. See the README file for configuration instructions.

Minor changes:

* Fix bugs in `BaseCscTestCase.check_bin_script` and update ``test_csc.py`` to call it.
* Removed our local copy of ``ddsutil.py``.

Requirements:

* black
* ts_idl 1
* ts_xml 4.7
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.3.0
------

Major changes:

* Add `BaseCscTestCase` as a useful base class for CSC unit tests.
  Update the unit tests to use it.

Minor changes:

* `DefaultingValidator` now handles defaults in sub-objects (one level deep).
* CSCs will now reject optional generic commands if not implemented (meaning there is no ``do_``\ *command* method for them), instead of silently ignoring them.
  The optional generic commands are ``abort``, ``enterControl``, ``setValue``, and the deprecated command ``setSimulationMode``.
* The ``action`` argument of `BaseCsc.assert_enabled` is now optional. There is no point to setting it when calling it from ``do_``\ *command* methods as the user knows what command was rejected.
* If a command is rejected because a CSC is in ``FAULT`` state, the error message contains the current value of the ``errorReport`` field of the ``errorCode`` event.
* `SalInfo` could not be created for a SAL component that had no commands (because such a component also has no ackcmd topic).

Deprecated APIs:

* ``lsst.ts.salobj.test_utils`` is deprecated. Please use ``lsst.ts.salobj`` instead.


Requirements:

* ts_idl 1
* ts_xml 4.6
* IDL files for Test, Script, and LOVE.
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.2.1
------

Fix a call to `warnings.warn` in `Domain`.

Requirements:

* ts_idl 1
* ts_xml 4.6
* IDL files for Test and Script
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.2.0
------

Major changes:

* CSCs no longer support the ``setSimulationMode`` command, as per RFC-639.

Deprecated APIs:

* BaseCsc and ConfigurableCsc: the ``initial_simulation_mode`` constructor argument is deprecated in favor of the new ``simulation_mode`` argument.
  It is an error to specify both.

v5.1.0
------

Major changes:

* Provide IDL metadata, including descriptions of topics and descriptions and units of fields, via a new `SalInfo` ``metadata`` attribute, an instance of `IdlMetadata`.
  Some of the metadata is only available in IDL files built with SAL 4.6.
* Add the `AsyncS3Bucket` class for writing to Amazon Web Services s3 buckets.

Minor changes:

* Change a link in the doc string for `BaseCsc.handle_summary_state` to avoid Sphinx errors in subclasses in other packages.
* Add a ``done_task`` attribute to `Domain`.
* Add an ``isopen`` attribute to `Controller`.
* Improve close methods for `Domain`, `SalInfo`, `Controller` and `Remote` to reduce warnings in unit tests.
  Subsequent calls wait until the first call finishes and `SalInfo` allows time for its read loop to finish.

Deprecated APIs:

* ``SalInfo.idl_loc`` should now be ``SalInfo.metadata.idl_path``.

Requirements:

* ts_idl 1
* IDL files for Test and Script
* SALPY_Test generated by ts_sal 4 (for unit tests)

v5.0.0
------

Update for ts_sal v4. This version cannot communicate with ts_sal v3 or ts_salobj v4 because of changes at the DDS level:

* The ``ackcmd`` topic has new fields that distinguish acknowledgements for commands sent by one `Remote` from those sent by another.
* Command topics and the ``ackcmd`` topic now have ``volatile`` durability instead of ``transient``.
  This means they cannot read late-joiner data, which eliminates a source of potential problems from stale commands or command acknowledgements.
* The DDS queues now hold 100 samples instead of 1000.

Another backward incompatible change is that the setSimulationMode command can no only be issued in the STANDBY state.
This makes it much easier to implement simulation mode in CSCs that connect to external controllers,
because one can make the connection in the appropriate mode when in DISABLED or ENABLED state, without having to worry about changing it.
This change may break some existing unit tests for CSCs that support simulation mode.

Deprecated APIs:

* Specifying ``code=None`` for `BaseCsc.fault` is deprecated. Please always specify an error code so the ``errorCode`` event can be output.
* `BaseCsc.main` and `BaseScript.main` are deprecated. Please replace ``cls.main(...)`` with ``asyncio.run(cls.amain(...))``.
  This makes it much clearer that the call may not return quickly, avoids explicitly creating event loops, and takes advantage of the (new to Python 3.7) preferred way to run asynchronous code.
* Setting ``BaseCsc.summary_state`` is deprecated.
  In unit tests use the standard state transition commands or call the `set_summary_state` function.
  In CSCs you should not be setting summary state directly; of the existing CSC code I've seen,
  most of it sends the CSC to a FAULT state, for which you should call `BaseCsc.fault`,
  and the rest doesn't need to set the summary state at all.
* Script commands ``setCheckpoints`` and ``setLogLevel`` are deprecated.
  Specify checkpoints and log level using the new ``pauseCheckpoint``, ``stopCheckpoint`` and ``logLevel`` fields in the ``configure`` command.
* Code that constructs a `Remote` or `Controller` without a running event loop should be rewritten because it will break when we replace the remaining usage of `asyncio.ensure_future` with the preferred `asyncio.create_task`. For example:

  .. code-block:: python

    csc = MyCscClass(...)
    asyncio.get_event_loop().run_until_complete(csc.done_task)

  can be replaced with (see `BaseCsc.make_from_cmd_line` to add command-line arguments):

  .. code-block:: python

    asyncio.run(MyCscClass.amain(...))

New capabilities:

* Add function `current_tai` to return the current time in TAI unix seconds (LSST's standard for SAL timestamps).
* Enhance function `tai_from_utc` to support alternate formats for UTC using new argument ``format="unix"``.
* Add `topics.ReadTopic.aget` to return the current sample, if any, else wait for the next sample (DM-20975).
* Add coroutine ``BaseCsc.handle_summary_state``.
  This is the preferred way to handle changes to summary state instead of overriding synchronous method `BaseCsc.report_summary_state`.
* Add property ``BaseCsc.disabled_or_enabled`` which returns true if the current summary state is `State.DISABLED` or `State.ENABLED`.
  This is useful in ``BaseCsc.handle_summary_state`` to determine if you should start or stop a telemetry loop.
* Add ``result_contains`` argument to `assertRaisesAckError`.
* Enhance `topics.ControllerCommand` automatic acknowledgement for callback functions so that the ``ack`` value is `SalRetCode`.CMD_ABORTED if the callback raises `asyncio.CancelledError` and `SalRetCode`.CMD_TIMEOUT if the callback raises `asyncio.TimeoutError`.
* `Controller.start` now waits for all remotes to start (except those constructed with ``start=False``, which is rare).
* Added ``start_called`` attribute to `SalInfo`, `Controller` and `Remote`.

Other improvements:

* Fix support for environment variable ``LSST_DDS_IP``.
  The value is now a dotted IP address; formerly it was an integer.
* Improve error handling when specifying a non-zero index for a non-indexed SAL component (DM-20976).
  The `SalInfo` constructor will now raise an exception.
* Improve error handling in `BaseCsc.fault`. Report the problem and continue if the error code is not an integer, or if `BaseCsc.report_summary_state` fails.
* The unit tests use the ``asynctest`` package, which is pip installable.
* The documentation for `BaseCsc.main` now recommends specifying ``index=None or 0`` for non-indexed components, instead of ``None or False``, in order to match standard usage in ts_salobj.
  All three values worked, and continue to work, but no existing code used `False`.
* Minor improvements to version handling:

    * Set ``lsst.ts.salobj.__version__`` to "?" if running directly from source and there is no ``version.py`` file generated by ``setup.py`` or ``scons``.
    * Update ``doc/conf.py`` to get ``__version__`` from ``lsst.ts.salobj`` instead of ``lsst.ts.salobj.version``.

* Stop reading dead topics because ts_sal 4 no longer disposes of any samples immediately after writing.
  This removes a workaround added in v4.3.0.
* Add this revision history.

Existing code is unlikely to require any changes to transition from salobj v4 to v5.

Communicates with ts_sal v4.

Requirements:

* ts_idl
* IDL files for Test and Script
* SALPY_Test generated by ts_sal v4 (for unit tests)

v4.5.0
------

Minor updates for ts_watcher and ts_salkafka:

* Add several name attributes to topics:

    * ``sal_name``: the name used by SAL for a topic, e.g. "logevent_summaryState".
    * ``attr_name``: the name used by ts_salobj for topic attributes of `Remote` and `Controller` e.g. "evt_summaryState".
    * ``dds_name``: the name used by DDS for a topic, e.g. "Test_logevent_summaryState_90255bf1".
    * ``rev_code``: the revision code that SAL appends to DDS topic names, e.g. "90255bf1".

* Remove the ``attr_prefix`` attribute from topics.

Communicates with ts_sal v3.10 (but not 3.9).

Requirements:

* ts_idl
* IDL files for Test and Script
* SALPY_Test generated by ts_sal v3.10 (for unit tests)

v4.4.0
------

Minor updates for ts_watcher:

* Add support to `Remote` for adding topics after the object is constructed:

    * Change the meaning of constructor argument ``include=[]`` to include no topics.
      Formerly it would include all topics.
    * Add constructor argument ``start`` which defaults to True for backwards compatibility.
      Set it False if you want to add topics after constructing the remote.

* Add function `name_to_name_index` for parsing SAL component names of the form ``name[:index]``.
* Add ``attr_prefix`` attribute to `topics.BaseTopic`.
  Warning: this was replaced by ``attr_name`` in v4.5.0.

Communicates with ts_sal 3.10 (but not 3.9).

Requirements:

* ts_idl
* IDL files for Test and Script
* SALPY_Test generated by ts_sal v3.10 (for unit tests)

v4.3.1
------

Make the unit test pass more reliably.

Warning: the unit tests only pass reliably if run using ``pytest``.
I still see a failure roughly 1/4 of the time when run using ``scons``.
This is probably a side effect of enabling code coverage analysis.

Other changes:

* Make ``scons`` optional by moving bin scripts from ``bin.src/`` to ``bin/`` and making ``version.py`` optional.
* Modify `BaseCsc.set_summary_state` to return a list of summary states.
  This is mostly for the sake of unit tests but it also tells callers what state the CSC started in.


Requirements:

* ts_idl
* IDL files for Test and Script
* SALPY_Test generated by ts_sal v3.10 (for unit tests)

v4.3.0
------

The first version that is truly compatible with ts_sal 3.10.

Fix an incompatibility with SAL 3.10:

* salobj could not reliably read ackcmd and command topics sent by SAL 3.10 because SAL 3.10 disposes those samples immediately after writing.
  Fixed by reading dead samples for those topics.
  This is intended as a temporary change until ts_sal is updated to not dispose samples after writing.
* Added a unit test for salobj<->SAL communication.
  Thus ts_sal is now an optional dependency of ts_salobj.

Requirements:
- ts_idl 0.1
- SALPY_Test generated by ts_sal 3.10 (for unit tests)

v4.2.0
------

Warning: do not use this version because it is not compatible with ts_sal. Use v4.3.0 or later.

Add BaseScript (moved from ts_scriptqueue).


v4.1.1
------

Warning: do not use this version because it is not compatible with ts_sal. Use v4.3.0 or later.

Do not warn about the config labels file if empty.
Only warn if the config labels file has data and that data cannot be parsed as a dict.

Other changes:

* Update log.warn to log.warning to fix deprecation warnings.


v4.1.0
------

Warning: do not use this version because it is not compatible with ts_sal. Use v4.3.0 or later.

Add ``evt_max_history`` and ``tel_max_history arguments`` to `Remote` constructor.

v4.0.0
------

Warning: do not use this version because it is not compatible with ts_sal. Use v4.3.0 or later.

Compete rewrite to use OpenSplice dds instead of SALPY libraries generated by ts_sal.
For more information see https://community.lsst.org/t/changes-in-salobj-4-the-dds-version/3701

To generate IDL files use command-line script ``make_idl_files.py`` which is available in ts_sal 3.10.
For example::

    make_idl_files.py Test Script
