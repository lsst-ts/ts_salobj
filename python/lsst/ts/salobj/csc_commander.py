# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
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
import functools
import sys

from . import domain
from . import remote
from . import sal_enums
from . import csc_utils

STD_TIMEOUT = 60


async def stream_as_generator(stream, encoding="utf-8"):
    """Await lines of text from stdin or another input stream.

    Example usage:

        async for line in stream_as_generator(stream=sys.stdin):
            print(f"read {repr(line)}")

    Parameters
    ----------
    stream : ``stream``
        Stream to read, e.g. `sys.stdin`.
    encoding : `str` or `None`
        Encoding. If provided then decode the line,
        else return the line as raw bytes.

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
        if encoding is not None:
            line = line.decode(encoding)
        yield line


def round_any(value, digits=4):
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
    exclude : `List` [`str`] or `None`, optional
        Names of telemetry or event topics to not print.
        If `None` or empty then no topics are excluded.
    fields_to_ignore : `List` [`str`], optional
        SAL topic fields to ignore when specifying command parameters,
        and when printing events and telemetry.
    enable : `bool`, optional
        Enable the CSC (when the commander starts up)?
        Note: `amain` always supplies this argument.

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

    Unit Testing
    ------------
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
        name,
        index=0,
        enable=False,
        exclude=None,
        fields_to_ignore=("ignored", "value", "priority"),
    ):
        self.domain = domain.Domain()
        self.remote = remote.Remote(
            domain=self.domain, name=name, index=index, exclude=exclude
        )
        self.fields_to_ignore = set(fields_to_ignore)
        self.tasks = set()
        self.help_dict = dict()
        self.enable = enable
        self.testing = False
        self.output_queue = collections.deque()

        for name in self.remote.salinfo.event_names:
            if name == "heartbeat":
                continue
            topic_name = f"evt_{name}"
            topic = getattr(self.remote, topic_name)
            callback = getattr(self, f"{topic_name}_callback", None)
            if callback is None:
                callback = functools.partial(self.event_callback, name=name)
            setattr(topic, "callback", callback)

        for name in self.remote.salinfo.telemetry_names:
            topic_name = f"tel_{name}"
            setattr(self, f"previous_{topic_name}", None)
            topic = getattr(self.remote, topic_name)
            callback = getattr(self, f"{topic_name}_callback", None)
            if callback is None:
                callback = functools.partial(self.telemetry_callback, name=name)
            setattr(topic, "callback", callback)

        # Dict of command name: RemoteCommand topic:
        self.command_dict = {
            name: getattr(self.remote, f"cmd_{name}")
            for name in self.remote.salinfo.command_names
        }

    def print_help(self):
        """Print help.
        """
        command_help = "\n".join(self.get_commands_help())
        self.output(
            f"""Send commands to the {self.remote.salinfo.name} CSC and print events and telemetry.

CSC Commands:
{command_help}
exit  # exit this commander (leaving the CSC running)
help  # print this help
"""
        )

    async def close(self):
        """Close the commander, prior to quitting.
        """
        while self.tasks:
            task = self.tasks.pop()
            task.cancel()
        await self.remote.close()
        await self.domain.close()

    def output(self, str):
        """Print a string to output, appending a final newline.

        Please call this instead of print to support unit tests.

        If ``self.testing`` is True then append ``str`` to
        ``self.output_queue`` instead of printing it.
        Use this mode for unit testing a CSC commander.
        """
        if self.testing:
            self.output_queue.append(str)
        print(str)

    def format_item(self, key, value):
        """Format one event or telemetry field for printing.
        """
        if isinstance(value, float):
            return f"{key}={value:0.4f}"
        return f"{key}={value}"

    def format_data(self, data):
        """Format an event or telemetry sample for printing.
        """
        return ", ".join(
            self.format_item(key, value)
            for key, value in self.get_public_data(data).items()
        )

    def field_is_public(self, name):
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

    def get_public_data(self, data):
        """Return a dict of field_name: value for public fields.

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

    def get_rounded_public_fields(self, data, digits=4):
        """Get the public fields for a sample, with float values rounded.
        """
        return {
            key: round_any(value, digits=digits)
            for key, value in data.get_vars().items()
            if self.field_is_public(key)
        }

    def event_callback(self, data, name):
        """Generic callback for events.

        You may provide evt_<event_name> methods to override printing
        of specific events.
        """
        self.output(f"{data.private_sndStamp:0.3f}: {name}: {self.format_data(data)}")

    def evt_summaryState_callback(self, data):
        try:
            state = sal_enums.State(data.summaryState)
        except Exception:
            state = f"{data.summaryState} (not a known state!)"
        self.output(
            f"{data.private_sndStamp:0.3f}: summaryState: summaryState={state!r}"
        )

    def telemetry_callback(self, data, name):
        """Generic callback for telemetry.

        You may provide tel_<telemetry_name> methods to override printing
        of specific telemetry topics.
        """
        prev_value_name = f"previous_tel_{name}"
        public_fields = self.get_rounded_public_fields(data)
        if public_fields != getattr(self, prev_value_name):
            setattr(self, prev_value_name, public_fields)
            formatted_data = ", ".join(
                f"{key}={value}" for key, value in public_fields.items()
            )
            self.output(f"{data.private_sndStamp:0.3f}: {name}: {formatted_data}")

    def check_arguments(self, args, *names):
        """Check that the required arguments are provided,
        and return them as a keyword argument dict with cast values.

        Parameters
        ----------
        args : `List` [`str`]
            Command arguments, as strings.
        *names : `List` [`str` or `tuple`]
            Argument name and optional cast function. Each element is either:

            * An argument name, in which case the argument is cast to a float
            * A tuple of (name, cast function), in which case the argument
                is cast using the cast function.
        """
        required_num_args = len(names)
        if len(args) != required_num_args:
            if required_num_args == 0:
                raise RuntimeError("no arguments allowed")
            else:
                raise RuntimeError(
                    f"{required_num_args} arguments required:  "
                    f"{names}; {len(args)} provided."
                )

        def cast(name, arg):
            if isinstance(name, tuple):
                if len(name) != 2:
                    raise RuntimeError(
                        "Cannot parse {name} as (name, casting function)"
                    )
                arg_name, cast_func = name
                return (arg_name, cast_func(arg))
            else:
                return (name, float(arg))

        return dict(cast(name, arg) for name, arg in zip(names, args))

    async def do_start(self, args):
        """Allow the start command to have no arguments.
        """
        assert len(args) in (0, 1)
        if args:
            settingsToApply = args[0]
        else:
            settingsToApply = ""
        await self.remote.cmd_start.set_start(
            settingsToApply=settingsToApply, timeout=STD_TIMEOUT
        )

    def get_commands_help(self):
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
                public_data = self.get_public_data(sample)
                field_names_str = " ".join(public_data.keys())
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

    async def run_command_topic(self, command_name, args):
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
            raise RuntimeError(
                f"Command {command_name} requires "
                f"{len(kwargs)} arguments; got {len(args)}"
            )
        for (name, default_value), str_value in zip(kwargs.items(), args):
            kwargs[name] = type(default_value)(str_value)
        await command.set_start(**kwargs)

    async def run_command(self, cmd):
        """Run the specified command string and wait for it to finish.

        Parameters
        ----------
        cmd : `str`
            Command string (command name and arguments).
            Note: does not handle the "exit" command.
        """
        tokens = cmd.split()
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

    async def _run_command_and_output(self, cmd):
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

    async def start(self):
        """Start asynchonous processes.
        """
        self.output(f"Waiting for {self.remote.salinfo.name_index} to start.")
        await self.remote.start_task
        if self.enable:
            self.output(f"Enabling {self.remote.salinfo.name_index}")
            # Temporarily remove the ``evt_summaryState`` callback
            # so the `set_summary_state` function can read the topic.
            summary_state_callback = self.remote.evt_summaryState.callback
            try:
                self.remote.evt_summaryState.callback = None
                await csc_utils.set_summary_state(self.remote, sal_enums.State.ENABLED)
            finally:
                summary_state = self.remote.evt_summaryState.get()
                if summary_state is not None:
                    summary_state_callback(summary_state)
                self.remote.evt_summaryState.callback = summary_state_callback

    @classmethod
    async def amain(cls, *, index, **kwargs):
        """Construct the commander and run it.

        Parse the command line to construct the commander,
        then parse and execute commands until the ``exit`` is seen.

        Parameters
        ----------
        index : `int`, `True`, `False` or `None`
            If the CSC is indexed: specify `True` make index a required
            command line argument, or specify a non-zero `int` to use
            that index.
            If the CSC is not indexed: specify `None` or 0.
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
                # Strip trailing comment, if any.
                if "#" in line:
                    line = line.split("#", maxsplit=1)[0].strip()
                if not line:
                    continue
                if line == "exit":
                    break
                task = asyncio.create_task(self._run_command_and_output(line))
                self.tasks.add(task)
        finally:
            await self.close()

    @classmethod
    def add_arguments(cls, parser):
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
    def add_kwargs_from_args(cls, args, kwargs):
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
    def make_from_cmd_line(cls, index, **kwargs):
        """Construct a SAL-related class from command line arguments.

        Parameters
        ----------
        index : `int`, `True`, `False` or `None`
            If the SAL component is indexed: specify `True` to make index
            a required command line argument,
            or specify a non-zero `int` to use that index.
            If the SAL component is not indexed: specify `None` or 0.
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

    async def __aenter__(self):
        await self.remote.start_task
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()
