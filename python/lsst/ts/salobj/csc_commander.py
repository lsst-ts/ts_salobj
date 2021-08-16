from __future__ import annotations

# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["stream_as_generator", "CscCommander"]

import argparse
import asyncio
import collections
import enum
import functools
import shlex
import sys
import types
import typing
import warnings

from . import domain
from . import remote
from . import sal_enums
from . import csc_utils
from . import type_hints

# A dict of valid values for bool command arguments.
# The argument should be converted to lowercase before using.
BOOL_DICT = {
    "0": False,
    "f": False,
    "false": False,
    "1": True,
    "t": True,
    "true": True,
}


async def stream_as_generator(
    stream: typing.TextIO, encoding: str = "utf-8"
) -> typing.AsyncGenerator[str, None]:
    """Await lines of text from stdin or another input stream.

    Example usage:

        async for line in stream_as_generator(stream=sys.stdin):
            print(f"read {repr(line)}")

    Parameters
    ----------
    stream : ``stream``
        Stream to read, e.g. `sys.stdin`.
    encoding : `str`
        Encoding.

    Returns
    -------
    line : `str`
        A line of data, optionally decoded.

    Notes
    -----
    Thanks to
    http://blog.mathieu-leplatre.info/some-python-3-asyncio-snippets.html
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(loop=loop)
    reader_protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: reader_protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:  # EOF.
            break
        yield line.decode(encoding)


def round_any(
    value: typing.Any,
    digits: int = 2,
) -> typing.Any:
    """Round any value to the specified number of digits.

    This is a no-op for int and str values.

    Notes
    -----
    This is designed for use with DDS samples. As such, it expects
    array values to be of type `list`.
    """
    if isinstance(value, float):
        return round(value, digits)
    elif value and isinstance(value, list) and isinstance(value[0], float):
        return [round(item, digits) for item in value]
    return value


class CscCommander:
    """Command a CSC from the command line.

    Parameters
    ----------
    name : `str`
        SAL component name of CSC.
    index : `int`, optional
        SAL index of CSC.
    enable : `bool`, optional
        Enable the CSC (when the commander starts up)?
        Note: `amain` always supplies this argument.
    exclude : `List` [`str`] or `None`, optional
        Names of telemetry or event topics to not print.
        If `None` or empty then no topics are excluded.
    exclude_commands : `List` [`str`], optional
        Names of commands to ignore. Typically this should include:

        * "abort" and "setValue", two generic commands that few CSCs implement.
        * "enterControl" unless your CSC is "externally commandable",
          meaning it can run in the OFFLINE state.

        The default is to exclude nothing, for backwards compatibility.
    fields_to_ignore : `List` [`str`], optional
        SAL topic fields names to ignore when specifying command parameters,
        and when printing events and telemetry.
    telemetry_fields_to_not_compare : `List` [`str`], optional
        Telemetry field names to ignore when checking if a telemetry topic has
        changed enough to print the latest sample. These fields are printed.

    Attributes
    ----------
    domain : `Domain`
        DDS domain.
    remote : `Remote`
        Remote for the CSC being commanded.
    help_dict : `dict`
        Dict of command_name: documentation.
        You should add one entry for every do_command method you define.
        Each documentation string should start with a list of argument names
        (the command name will be prepended for you)
        optionally followed by # and a brief description.
        The documentation string should a single line, if practical.


    Notes
    -----
    Warning: use with caution. Running a commander may interfere with
    telescope operations! If you provide a command-line script in ``bin/``
    that runs a commander, consider picking a name that is obscure
    and not easily confused with the script that runs the CSC.

    Make a subclass of `CscCommander` if you want to add extra commands
    or provide special handling for some commands, events or telemetry.
    Subclasses may provide overrides as follows:

    * To hide unwanted commands: delete them from ``self.command_dict``
      in your constructor. Most CSCs should hide the "abort", "enterControl"
      and "setValue" commands, as follows::

        for command_to_ignore in ("abort", "enterControl", "setValue"):
            del self.command_dict[command_to_ignore]

    * To override handling of a standard command (one defined in the XML):
      define a ``do_<command_name>`` method.
      The method receives one argument: a list of str arguments.
      You should provide a custom handler for, or hide, any command with
      array parameters, because the command parser only accepts scalars.

    * To add an additional command (one not defined in the XML):

        * Define a  ``do_<command_name>`` to handle the command.
          The method receives one argument: a list of str arguments.

        * Add an entry to ``help_dict``. The key is the command name
          and the value is a brief (preferably only one line) help string
          that lists the arguments first, and a brief description after.
          Here is an example::

            self.help_dict["sine"] = "start_position amplitude "
            "# track one cycle of a sine wave",

    * To override handling of an event or telemetry topic: define method
      ``evt_<event_name>_callback`` or ``tel_<event_name>_callback``,
      respectively.  It receives one argument: the DDS sample.
      This can be especially useful if the default behavior is too chatty
      for one or more telemetry topics.

    I have not found a way to write a unit test for this class.
    I tried running a commander in a subprocess but could not figure out
    how to send multiple commands (the ``suprocess.communicate``
    method only allows sending one item of data).
    Instead I suggest manually running it to control the Test CSC.

    Examples
    --------

    You can do a lot with just the base class. This command-line script
    will control the Test CSC pretty well::

        import asyncio
        from lsst.ts import salobj
        asyncio.run(salobj.CscCommander.amain(name="Test", index=True))

    However, this will claim to support some generic commands that the
    Test CSC does not support ( "abort", "enterControl", and "setValue")
    and it mishandles the "setArrays" command.
    See `TestCscCommander` for a version that fixes these deficiencies.
    `TestCscCommander` is run as follows::

        import asyncio
        from lsst.ts import salobj
        asyncio.run(salobj.TestCscCommander.amain(index=True))

    For an example with extra commands and special telemetry handling,
    see ``RotatorCommander`` in the ts_rotator package.

    **Unit Testing**

    To unit test a commander:

    * Set ``commander.testing = True``.
      This appends all output messages to output queue
      ``commander.output_queue``, a `collections.deque`.
      The messages are also printed to ``stdout``, as usual.
    * Call ``commander.run_command`` to run a command.
    * Check the output using the output queue.
    * Clear the output queue with ``commander.output_queue.clear()``
      whenever you like, e.g. before running a command whose output
      you want to check.
    """

    def __init__(
        self,
        name: str,
        index: typing.Optional[int] = 0,
        enable: bool = False,
        exclude: typing.Optional[typing.Sequence[str]] = None,
        exclude_commands: typing.Sequence[str] = (),
        fields_to_ignore: typing.Sequence[str] = ("ignored", "value", "priority"),
        telemetry_fields_to_not_compare: typing.Sequence[str] = ("timestamp",),
    ) -> None:
        self.domain = domain.Domain()
        self.remote = remote.Remote(
            domain=self.domain, name=name, index=index, exclude=exclude
        )
        self.fields_to_ignore = frozenset(fields_to_ignore)
        self.telemetry_fields_to_not_compare = frozenset(
            telemetry_fields_to_not_compare
        )
        self.tasks: typing.Set[asyncio.Future] = set()
        self.help_dict: typing.Dict[str, str] = dict()
        self.enable = enable
        self.testing = False
        self.output_queue: typing.Deque[str] = collections.deque()

        for name in self.remote.salinfo.event_names:
            if name == "heartbeat":
                continue
            topic_attr_name = f"evt_{name}"
            topic = getattr(self.remote, topic_attr_name)
            callback = getattr(self, f"{topic_attr_name}_callback", None)
            if callback is None:
                callback = functools.partial(self.event_callback, name=name)
            setattr(topic, "callback", callback)

        for name in self.remote.salinfo.telemetry_names:
            topic_attr_name = f"tel_{name}"
            setattr(self, f"previous_{topic_attr_name}", None)
            topic = getattr(self.remote, topic_attr_name)
            callback = getattr(self, f"{topic_attr_name}_callback", None)
            if callback is None:
                callback = functools.partial(self.telemetry_callback, name=name)
            setattr(topic, "callback", callback)

        # Dict of command name: RemoteCommand topic:
        self.command_dict = {
            name: getattr(self.remote, f"cmd_{name}")
            for name in self.remote.salinfo.command_names
            if name not in frozenset(exclude_commands)
        }

    def print_help(self) -> None:
        """Print help."""
        command_help = "\n".join(self.get_commands_help())
        self.output(
            f"""Send commands to the {self.remote.salinfo.name} CSC and print events and telemetry.

CSC Commands:
{command_help}
exit  # exit this commander (leaving the CSC running)
help  # print this help
"""
        )

    async def close(self) -> None:
        """Close the commander, prior to quitting."""
        while self.tasks:
            task = self.tasks.pop()
            task.cancel()
        await self.remote.close()
        await self.domain.close()

    def output(self, msg: str) -> None:
        """Print a message to output, appending a final newline.

        Please call this instead of print to support unit tests.

        If ``self.testing`` is True then append ``str`` to
        ``self.output_queue`` instead of printing it.
        Use this mode for unit testing a CSC commander.
        """
        if self.testing:
            self.output_queue.append(msg)
        print(msg)

    def format_item(self, key: str, value: typing.Any) -> str:
        """Format one event or telemetry field for printing."""
        if isinstance(value, float):
            return f"{key}={value:0.4f}"
        return f"{key}={value}"

    def format_data(self, data: typing.Any) -> str:
        """Format the public fields of an event or telemetry sample,
        for printing.
        """
        return self.format_dict(self.get_public_data(data))

    def format_dict(self, data: typing.Any) -> str:
        """Format a dict for printing.

        Unlike format_data, this requires a dict and formats *all* fields.
        """
        return ", ".join(self.format_item(key, value) for key, value in data.items())

    def field_is_public(self, name: str) -> bool:
        """Return True if the specified field name is public,
        False otherwise.
        """
        if name.startswith("private_"):
            return False
        if name == f"{self.remote.salinfo.name}ID":
            return False
        if name in self.fields_to_ignore:
            return False
        return True

    def get_public_data(self, data: typing.Any) -> typing.Dict[str, typing.Any]:
        """Get a dict of field_name: value for public fields of a DDS sample.

        Parameters
        ----------
        data : ``dds_sample``
            DDS sample.
        """
        return dict(
            (key, value)
            for key, value in data.get_vars().items()
            if self.field_is_public(key)
        )

    def get_rounded_public_data(self, data: typing.Any, digits: int = 2) -> typing.Any:
        """Get a dict of field_name: value for public fields of a DDS sample
        with float values rounded.
        """
        return {
            key: round_any(value, digits=digits)
            for key, value in data.get_vars().items()
            if self.field_is_public(key)
        }

    def get_rounded_public_fields(
        self, data: typing.Any, digits: int = 2
    ) -> typing.Any:
        """Deprecated version of get_rounded_public_data."""
        warnings.warn("Use get_rounded_public_data instead", DeprecationWarning)
        return self.get_rounded_public_data(data=data, digits=digits)

    def event_callback(self, data: typing.Any, name: str) -> None:
        """Generic callback for events.

        You may provide evt_<event_name> methods to override printing
        of specific events.
        """
        self.output(f"{data.private_sndStamp:0.3f}: {name}: {self.format_data(data)}")

    def evt_summaryState_callback(self, data: type_hints.BaseDdsDataType) -> None:
        state_int: int = data.summaryState  # type: ignore
        try:
            state_repr: str = repr(sal_enums.State(state_int))
        except Exception:
            state_repr = f"{state_int} (not a known state!)"
        self.output(
            f"{data.private_sndStamp:0.3f}: summaryState: summaryState={state_repr}"
        )

    def telemetry_callback(self, data: typing.Any, name: str, digits: int = 2) -> None:
        """Generic callback for telemetry.

        You may provide tel_<telemetry_name> methods to override printing
        of specific telemetry topics.
        """
        prev_value_name = f"previous_tel_{name}"
        public_dict = self.get_rounded_public_data(data, digits=digits)
        trimmed_dict = {
            name: value
            for name, value in public_dict.items()
            if name not in self.telemetry_fields_to_not_compare
        }
        if trimmed_dict != getattr(self, prev_value_name):
            setattr(self, prev_value_name, trimmed_dict)
            formatted_data = self.format_dict(public_dict)
            self.output(f"{data.private_sndStamp:0.3f}: {name}: {formatted_data}")

    def check_arguments(
        self,
        args: typing.Sequence[str],
        *names: typing.Union[
            str, typing.Tuple[str, typing.Callable[[str], typing.Any]]
        ],
    ) -> typing.Dict[str, typing.Any]:
        """Check that the required arguments are provided.
        and return them as a keyword argument dict with cast values.

        Parameters
        ----------
        args : `List` [`str`]
            Command arguments, as strings.
        *names : `List` [`str` or `tuple`]
            Argument name and optional cast function. Each element is either:

            * An argument name, in which case the argument is cast to a float
            * A tuple of (name, cast function), in which case the argument
              is cast using the cast function. The cast function takes
              one str argument and returns the cast value.
        """
        required_num_args = len(names)
        if len(args) != required_num_args:
            if required_num_args == 0:
                raise RuntimeError("no arguments allowed")
            else:
                raise RuntimeError(
                    f"{required_num_args} arguments required: {names}; "
                    f"{len(args)} arguments provided: {args}."
                )

        def cast(
            arg: str,
            name: typing.Union[
                str, typing.Tuple[str, typing.Callable[[str], typing.Any]]
            ],
        ) -> typing.Tuple[str, typing.Any]:
            """Cast one argument to the required type.

            Parameters
            ----------
            arg : `str`
                Argument value.
            name : `str` or (str, cast_func)
                Argument name and optional cast function; either:

                * An argument name, in which case ``arg`` is cast to a float
                * A tuple of (name, cast function), in which case ``arg``
                  is cast using the cast function. The cast function takes
                  one str argument and returns the cast value.

            Returns
            -------
            name_value : tuple
                A tuple of two values:

                * argument name (str)
                * cast value
            """
            if isinstance(name, tuple):
                if len(name) != 2:
                    raise RuntimeError(
                        "Cannot parse {name} as (name, casting function)"
                    )
                arg_name, cast_func = name
                return (arg_name, cast_func(arg))
            else:
                return (name, float(arg))

        return dict(cast(arg=arg, name=name) for name, arg in zip(names, args))

    async def do_start(self, args: typing.Sequence[str]) -> None:
        """Allow the start command to have no arguments."""
        assert len(args) in (0, 1)
        if args:
            settingsToApply = args[0]
        else:
            settingsToApply = ""
        await self.remote.cmd_start.set_start(  # type: ignore
            settingsToApply=settingsToApply,
        )

    def get_commands_help(self) -> typing.List[str]:
        """Get help for each command, as a list of strings.

        End with "Other Commands:" and any commands
        in help_dict that are not in command_dict.
        """
        help_strings = []
        for command_name in sorted(self.command_dict.keys()):
            field_names_str = self.help_dict.get(command_name, None)
            if field_names_str is None:
                command_topic = self.command_dict[command_name]
                sample = command_topic.DataType()
                public_dict = self.get_public_data(sample)
                field_names_str = " ".join(public_dict.keys())
            help_strings.append(f"{command_name} {field_names_str}")

        other_command_names = sorted(
            command_name
            for command_name in self.help_dict
            if command_name not in self.command_dict
        )
        help_strings += ["", "Other Commands:"]
        help_strings += [
            f"{command_name} {self.help_dict[command_name]}"
            for command_name in other_command_names
        ]
        return help_strings

    async def run_command_topic(
        self, command_name: str, args: typing.Sequence[str]
    ) -> None:
        """Run a command that has an associated salobj RemoteCommand topic.

        Parameters
        ----------
        command_name : `str`
            Command name, e.g. Enable
        args : `List` [`str`]
            String arguments for the command.
            There must be exactly one argument per public fields.

        Notes
        -----
        This method works for command topics that take scalar arguments.
        To support command topics with more exotic arguments you must
        provide a do_<command> method that parses the arguments
        and add an entry to self.help_dict.
        """
        command = self.command_dict[command_name]
        sample = command.DataType()
        kwargs = self.get_public_data(sample)
        if len(kwargs) != len(args):
            raise ValueError(
                f"Command {command_name} requires "
                f"{len(kwargs)} arguments; got {len(args)}"
            )
        for (name, default_value), str_value in zip(kwargs.items(), args):
            try:
                if type(default_value) is bool:
                    kwargs[name] = BOOL_DICT[str_value.lower()]
                else:
                    kwargs[name] = type(default_value)(str_value)
            except Exception:
                raise ValueError(
                    f"Could not parse value {str_value!r} "
                    f"as type {type(default_value).__name__} "
                    f"for argument {name}"
                )
        await command.set_start(**kwargs)

    async def run_command(self, cmd: str) -> None:
        """Run the specified command string and wait for it to finish.

        Parameters
        ----------
        cmd : `str`
            Command string (command name and arguments).
            Note: does not handle the "exit" command.
        """
        tokens = shlex.split(cmd)
        command_name = tokens[0]
        args = tokens[1:]
        command_method = getattr(self, f"do_{command_name}", None)
        coro = None
        if command_name == "help":
            self.print_help()
        elif command_method is not None:
            coro = command_method(args)
        elif command_name in self.command_dict:
            coro = self.run_command_topic(command_name, args)
        else:
            self.output(f"Unrecognized command: {command_name}")

        if coro is None:
            return
        await coro

    async def _run_command_and_output(self, cmd: str) -> None:
        """Execute a command and wait for it to finish. Output the result.

        A wrapper around `run_command` that adds a task to self.tasks
        and catches and outputs exceptions. For use by the interactive
        command loop.

        Parameters
        ----------
        cmd : `str`
            Command string (command name and arguments).
            Note: does not handle the "exit" command.
        """
        task = asyncio.create_task(self.run_command(cmd))
        self.tasks.add(task)
        try:
            await task
            command_name = cmd.split()[0]
            self.output(f"Finished command {command_name}")
        except Exception as e:
            self.output(str(e))
        finally:
            self.tasks.remove(task)

    async def start(self) -> None:
        """Start asynchonous processes."""
        self.output(f"Waiting for {self.remote.salinfo.name_index} to start.")
        await self.remote.start_task
        if self.enable:
            self.output(f"Enabling {self.remote.salinfo.name_index}")
            # Temporarily remove the ``evt_summaryState`` callback
            # so the `set_summary_state` function can read the topic.
            summary_state_callback = self.remote.evt_summaryState.callback  # type: ignore
            try:
                self.remote.evt_summaryState.callback = None  # type: ignore
                await csc_utils.set_summary_state(self.remote, sal_enums.State.ENABLED)
            finally:
                summary_state = self.remote.evt_summaryState.get()  # type: ignore
                if summary_state is not None:
                    summary_state_callback(summary_state)
                self.remote.evt_summaryState.callback = summary_state_callback  # type: ignore

    @classmethod
    async def amain(
        cls, *, index: typing.Union[int, enum.IntEnum, bool, None], **kwargs: typing.Any
    ) -> None:
        """Construct the commander and run it.

        Parse the command line to construct the commander,
        then parse and execute commands until the ``exit`` is seen.

        Parameters
        ----------
        index : `int`, `enum.IntEnum`, `True`, or `None`
            If the CSC is indexed, do one of the following:

            * Specify `True` to make ``index`` a required
              command-line argument that accepts any nonzero index.
            * Specify an `enum.IntEnum` *class* to make ``index`` a required
              command-line argument that only accepts the enum values.
            * Specify a non-zero integer to use that index.
              This is rare; if the CSC is indexed then the user
              should usually be allowed to specify the index.

            If the CSC is not indexed, specify `None` or 0.
        **kwargs : `dict`, optional
            Additional keyword arguments for your CSC's constructor.
        """
        self = cls.make_from_cmd_line(index=index, **kwargs)
        try:
            await self.start()

            self.print_help()
            async for line in stream_as_generator(sys.stdin):
                # Purge done tasks
                self.tasks = {task for task in self.tasks if not task.done()}

                # Execute the new command
                line = line.strip()
                if not line:
                    continue
                if line == "exit":
                    break
                task = asyncio.create_task(self._run_command_and_output(line))
                self.tasks.add(task)
        finally:
            await self.close()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add arguments to the parser created by `make_from_cmd_line`.

        Parameters
        ----------
        parser : `argparse.ArgumentParser`
            The argument parser.

        Notes
        -----
        If you override this method then you should almost certainly override
        `add_kwargs_from_args` as well.
        """
        pass

    @classmethod
    def add_kwargs_from_args(
        cls, args: argparse.Namespace, kwargs: typing.Dict[str, typing.Any]
    ) -> None:
        """Add constructor keyword arguments based on parsed arguments.

        Parameters
        ----------
        args : `argparse.namespace`
            Parsed command.
        kwargs : `dict`
            Keyword argument dict for the constructor.
            Update this based on ``args``.
            The index argument will already be present if relevant.

        Notes
        -----
        If you override this method then you should almost certainly override
        `add_arguments` as well.
        """
        pass

    @classmethod
    def make_from_cmd_line(
        cls, index: typing.Union[int, enum.IntEnum, bool, None], **kwargs: typing.Any
    ) -> CscCommander:
        """Construct a SAL-related class from command line arguments.

        Parameters
        ----------
        index : `int`, `enum.IntEnum`, `True`, or `None`
            If the CSC is indexed, do one of the following:

            * Specify `True` to make ``index`` a required
              command-line argument that accepts any nonzero index.
            * Specify an `enum.IntEnum` *class* to make ``index`` a required
              command-line argument that only accepts the enum values.
            * Specify a non-zero integer to use that index.
              This is rare; if the CSC is indexed then the user
              should usually be allowed to specify the index.

            If the CSC is not indexed, specify `None` or 0.
        **kwargs : `dict`, optional
            Additional keyword arguments for your class's constructor.

        Returns
        -------
        instance : ``cls``
            The constructed instance.

        Notes
        -----
        To add additional command-line arguments, override `add_arguments`
        and `add_kwargs_from_args`.
        """
        parser = argparse.ArgumentParser(f"Run {cls.__name__}")
        if index is True:
            parser.add_argument("index", type=int, help="Script SAL Component index.")
        parser.add_argument(
            "-e", "--enable", action="store_true", help="Enable the CSC?"
        )
        cls.add_arguments(parser)

        args = parser.parse_args()
        if index is True:
            kwargs["index"] = args.index
        elif not index:
            pass
        else:
            kwargs["index"] = int(index)
        kwargs["enable"] = args.enable
        cls.add_kwargs_from_args(args=args, kwargs=kwargs)

        return cls(**kwargs)

    async def __aenter__(self) -> CscCommander:
        await self.remote.start_task
        return self

    async def __aexit__(
        self,
        type: typing.Optional[typing.Type[BaseException]],
        value: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ) -> None:
        await self.close()
