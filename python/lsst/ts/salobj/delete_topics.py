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

__all__ = ["delete_topics", "DeleteTopics", "DeleteTopicsArgs"]

import argparse
import asyncio
import dataclasses
import logging
import re
from typing import Self

from confluent_kafka.admin import AdminClient
from confluent_kafka.schema_registry import SchemaRegistryClient

from .domain import Domain
from .sal_info import SalInfo


@dataclasses.dataclass
class DeleteTopicsArgs:
    all_topics: bool
    subname: str
    force: bool
    dry: bool
    log_level: str | None
    components: list[str]

    @classmethod
    def from_args(cls) -> Self:
        parser = argparse.ArgumentParser(description="Utility to delete topics.")

        parser.add_argument(
            "components",
            nargs="*",
            help="Names of SAL components, e.g. 'Script ScriptQueue'. "
            "Ignored if --all is specified",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Delete topics for all components.",
        )
        parser.add_argument(
            "--subname",
            help="The topic subname to delete. "
            "If used in conjunction with '--all' it will delete all topics with the specified subname. "
            "If not provided assume all subnames should be deleted, "
            "except the 'sal' subname, which is special and requires "
            "users to pass '--force'.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Use this in conjunction with '--subname sal' if you "
            "need to delete topics in the 'sal' subname. "
            "The 'sal' subname is special as it is the one used in operations.",
        )
        parser.add_argument(
            "--dry",
            action="store_true",
            help="Run in dry mode. List steps only but do not perform any operation.",
        )
        parser.add_argument(
            "--log-level",
            help="Log level.",
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        )
        args = parser.parse_args()
        return cls(
            components=args.components,
            all_topics=args.all,
            subname=args.subname,
            force=args.force,
            dry=args.dry,
            log_level=args.log_level,
        )


class DeleteTopics:
    """Handle the process of deleting topics and schema from the
    Kafka brokers.
    """

    def __init__(
        self,
        admin_client: AdminClient,
        schema_registry_client: SchemaRegistryClient,
        log: logging.Logger | None = None,
    ) -> None:
        self.log = (
            logging.getLogger(type(self).__name__)
            if log is None
            else log.getChild(type(self).__name__)
        )
        self.admin_client = admin_client
        self.schema_registry_client = schema_registry_client

        self.topic_regexp = re.compile(
            r"lsst.(?P<subname>[a-zA-Z0-9_]*)."
            r"(?P<component>[a-zA-Z0-9_]*)."
            r"(?P<topic_name>[a-zA-Z0-9_]*)"
        )
        self.schema_regexp = re.compile(
            r"lsst.(?P<subname>[a-zA-Z0-9_]*)."
            r"(?P<component>[a-zA-Z0-9_]*)."
            r"(?P<topic_name>[a-zA-Z0-9_]*)-value"
        )

    @classmethod
    async def new(cls) -> Self:
        """Construct an instance of the class."""

        broker_configuration, schema_registry_url = await get_broker_info()

        admin_client = AdminClient(broker_configuration)

        schema_registry_client = SchemaRegistryClient(dict(url=schema_registry_url))

        return cls(
            admin_client=admin_client, schema_registry_client=schema_registry_client
        )

    def retrieve_topic_summary(self) -> dict[str, dict[str, str]]:
        """Retrieve a summary of the topics in the broker.

        Returns
        -------
        topics_summary : `dict`[`str`, `dict`[`str`, `str`]]
            Topic summary consisting of a dictionary with the
            topic name as key and a dictionary with the subname
            and component as value.
        """
        topics_registered = self.admin_client.list_topics()
        topics_summary = self.summarize_topics(topics_registered.topics)

        return topics_summary

    def retrieve_schema_summary(self) -> dict[str, dict[str, str]]:
        """Retrieve a summary of the topic schema in the schema registry.

        Returns
        -------
        schema_summary : `dict`[`str`, `dict`[`str`, `str`]]
            Topic schema summary consisting of a dictionary with the
            subject name as key and a dictionary with the subname
            and component as value.
        """
        subjects = self.schema_registry_client.get_subjects()
        schema_summary = self.summarize_schema(subjects)

        return schema_summary

    def summarize_topics(self, topic_list: list[str]) -> dict[str, dict[str, str]]:
        """Generate a summary from the list of topics."""
        sal_topics = dict()
        non_sal_topics = list()
        subnames = set()
        components = set()

        for topic in topic_list:
            topic_regexp_match = self.topic_regexp.search(topic)
            if topic_regexp_match is None:
                non_sal_topics.append(topic)
            else:
                topic_regexp_groupdict = topic_regexp_match.groupdict()
                subnames.add(topic_regexp_groupdict["subname"])
                components.add(topic_regexp_groupdict["component"])
                sal_topics[topic] = topic_regexp_groupdict

        self.log.info(
            f"Got {len(topic_list)} topics; {len(sal_topics)} sal topics and "
            f"{len(non_sal_topics)} non-sal topics.\n"
            f"Got {len(subnames)} subnames: {', '.join(subnames)}.\n"
            f"Got {len(components)} components: {', '.join(components)}."
        )

        return sal_topics

    def summarize_schema(self, subject_list: list[str]) -> dict[str, dict[str, str]]:
        """Generate a summary from the list of subjects."""
        sal_topics_schema = dict()
        non_sal_topics_schema = list()
        subnames = set()
        components = set()

        for topic in subject_list:
            topic_regexp_match = self.schema_regexp.search(topic)
            if topic_regexp_match is None:
                non_sal_topics_schema.append(topic)
            else:
                topic_regexp_groupdict = topic_regexp_match.groupdict()
                subnames.add(topic_regexp_groupdict["subname"])
                components.add(topic_regexp_groupdict["component"])
                sal_topics_schema[topic] = topic_regexp_groupdict

        self.log.info(
            f"Got {len(subject_list)} topics schema; {len(sal_topics_schema)} "
            f"for sal topics and {len(non_sal_topics_schema)} for non-sal topics.\n"
            f"Got {len(subnames)} subnames: {', '.join(subnames)}.\n"
            f"Got {len(components)} components: {', '.join(components)}."
        )

        return sal_topics_schema

    def delete_topics(self, topics_to_delete: list[str]) -> None:
        """Delete topics."""

        if not topics_to_delete:
            return

        for topic in topics_to_delete:
            self.assert_topic_has_no_consumers(topic=topic)

        delete_futures = self.admin_client.delete_topics(
            topics_to_delete, operation_timeout=60
        )
        for topic, future in delete_futures.items():
            try:
                future.result()
                self.log.debug(f"{topic=} deleted.")
            except Exception:
                self.log.exception(f"Failed to delete {topic=}.")

    def delete_schema(self, schema_to_delete: list[str]) -> None:
        """Delete schemas."""

        for subject in schema_to_delete:
            try:
                self.schema_registry_client.delete_subject(subject)
                self.log.debug(f"{subject=} preemptively removed.")
            except Exception:
                self.log.exception(f"Failed to preemptively delete {subject=}.")

        for subject in schema_to_delete:
            try:
                self.schema_registry_client.delete_subject(subject, permanent=True)
                self.log.debug(f"{subject=} permanently removed.")
            except Exception:
                self.log.exception(f"Failed to permanently delete {subject=}.")

    def assert_topic_has_no_consumers(self, topic: str) -> None:
        """Check if any consumer group has an assignment
        that includes the given topic.

        Raises
        ------
        AssertionError
            If topic has consumers.
        """
        groups = self.admin_client.list_consumer_groups().result()
        for group in groups.valid:
            group_id = group.group_id
            group_descs = self.admin_client.describe_consumer_groups([group_id])
            for desc in group_descs.values():
                for member in desc.result().members:
                    topics = [tp.topic for tp in member.assignment.topic_partitions]
                    assert (
                        topic not in topics
                    ), f"Found consumer in group '{group_id}' assigned to topic '{topic}'."

    def execute(self, delete_topics_args: DeleteTopicsArgs | None = None) -> None:
        """Execute the delete topic operation."""

        args = (
            DeleteTopicsArgs.from_args()
            if delete_topics_args is None
            else delete_topics_args
        )

        if args.log_level is not None:
            logging.basicConfig(level=getattr(logging, args.log_level))

        if (args.subname == "sal") and not args.force:
            raise RuntimeError(
                "In order to delete topics for the 'sal' subname, "
                "you must provide the '--force' argument. "
                "Beware that this is the subname used for deployment. "
                "You should not run it with this parameters unless you know what you are doing."
            )

        topics_summary = self.retrieve_topic_summary()
        schema_summary = self.retrieve_schema_summary()

        topics_to_delete = [
            topic
            for topic in topics_summary
            if (
                args.all_topics or topics_summary[topic]["component"] in args.components
            )
            and (
                (args.all_topics and topics_summary[topic]["subname"] != "sal")
                or topics_summary[topic]["subname"] == args.subname
            )
        ]

        schema_to_delete = [
            subject
            for subject in schema_summary
            if (
                args.all_topics
                or schema_summary[subject]["component"] in args.components
            )
            and (
                (args.all_topics and schema_summary[subject]["subname"] != "sal")
                or schema_summary[subject]["subname"] == args.subname
            )
        ]

        if not topics_to_delete and not schema_to_delete:
            self.log.info(f"No topics or schemas to delete: {args}")
            return

        topics_to_delete_msg = "\n".join(topics_to_delete)
        schema_to_delete_msg = "\n".join(schema_to_delete)
        self.log.info(
            f"""
Deleting {len(topics_to_delete)} topics: {topics_to_delete_msg}.
Deleting {len(schema_to_delete)} schemas: {schema_to_delete_msg}.
            """
        )

        if args.dry:
            self.log.info("Running in dry mode, exiting. No topics were deleted.")
            return

        self.delete_topics(topics_to_delete)
        self.delete_schema(
            schema_to_delete,
        )

    @classmethod
    async def arun(cls) -> None:
        delete_topics = await cls.new()
        delete_topics.execute()


def delete_topics() -> None:
    """Utility to delete topics."""
    asyncio.run(DeleteTopics.arun())


async def get_broker_info() -> tuple[dict[str, str], str]:
    """Retrieve basic broker information.

    Returns
    -------
    broker_configuration : `dict`[`str`, `str`]
        Broker configuration.
    schema_registry_url : `str`
        The schema registry url.
    """

    async with Domain() as d, SalInfo(d, "Test", 0) as salinfo:
        broker_configuration = salinfo.get_broker_client_configuration()
        schema_registry_url = salinfo.schema_registry_url
        return broker_configuration, schema_registry_url
