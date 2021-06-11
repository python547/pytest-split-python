import json
import heapq
import os
from typing import TYPE_CHECKING
from collections import namedtuple

import pytest
from _pytest.config import create_terminal_writer, hookimpl
from _pytest.reports import TestReport

if TYPE_CHECKING:
    from typing import List, Optional, Union, Dict, Tuple

    from _pytest import nodes
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.main import ExitCode

# Ugly hack for freezegun compatibility: https://github.com/spulec/freezegun/issues/286
STORE_DURATIONS_SETUP_AND_TEARDOWN_THRESHOLD = 60 * 10  # seconds

test_group = namedtuple("test_group", "selected, deselected, duration")


def pytest_addoption(parser: "Parser") -> None:
    """
    Declare pytest-split's options.
    """
    group = parser.getgroup(
        "Split tests into groups which execution time is about the same. "
        "Run with --store-durations to store information about test execution times."
    )
    group.addoption(
        "--store-durations",
        dest="store_durations",
        action="store_true",
        help="Store durations into '--durations-path'.",
    )
    group.addoption(
        "--durations-path",
        dest="durations_path",
        help=(
            "Path to the file in which durations are (to be) stored, "
            "default is .test_durations in the current working directory"
        ),
        default=os.path.join(os.getcwd(), ".test_durations"),
    )
    group.addoption(
        "--splits",
        dest="splits",
        type=int,
        help="The number of groups to split the tests into",
    )
    group.addoption(
        "--group",
        dest="group",
        type=int,
        help="The group of tests that should be executed (first one is 1)",
    )


@pytest.mark.tryfirst
def pytest_cmdline_main(config: "Config") -> "Optional[Union[int, ExitCode]]":
    """
    Validate options.
    """
    group = config.getoption("group")
    splits = config.getoption("splits")

    if splits is None and group is None:
        return None

    if splits and group is None:
        raise pytest.UsageError("argument `--group` is required")

    if group and splits is None:
        raise pytest.UsageError("argument `--splits` is required")

    if splits < 1:
        raise pytest.UsageError("argument `--splits` must be >= 1")

    if group < 1 or group > splits:
        raise pytest.UsageError(f"argument `--group` must be >= 1 and <= {splits}")

    return None


def pytest_configure(config: "Config") -> None:
    """
    Enable the plugins we need.
    """
    if config.option.splits and config.option.group:
        config.pluginmanager.register(PytestSplitPlugin(config), "pytestsplitplugin")

    if config.option.store_durations:
        config.pluginmanager.register(PytestSplitCachePlugin(config), "pytestsplitcacheplugin")


class Base:
    def __init__(self, config: "Config") -> None:
        """
        Load durations and set up a terminal writer.

        This logic is shared for both the split- and cache plugin.
        """
        self.config = config
        self.writer = create_terminal_writer(self.config)

        try:
            with open(config.option.durations_path, "r") as f:
                self.cached_durations = json.loads(f.read())
        except FileNotFoundError:
            self.cached_durations = {}

        # This code provides backwards compatibility after we switched
        # from saving durations in a list-of-lists to a dict format
        # Remove this when bumping to v1
        if isinstance(self.cached_durations, list):
            self.cached_durations = {test_name: duration for test_name, duration in self.cached_durations}


class PytestSplitPlugin(Base):
    def __init__(self, config: "Config"):
        super().__init__(config)

        if not self.cached_durations:
            message = self.writer.markup(
                "\n[pytest-split] No test durations found. Pytest-split will "
                "split tests evenly when no durations are found. "
                "\n[pytest-split] You can expect better results in consequent runs, "
                "when test timings have been documented.\n"
            )
            self.writer.line(message)

    @hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config: "Config", items: "List[nodes.Item]") -> None:
        """
        Collect and select the tests we want to run, and deselect the rest.
        """
        splits: int = config.option.splits
        group_idx: int = config.option.group

        groups = split_tests(splits, items, self.cached_durations)
        group = groups[group_idx - 1]

        items[:] = group.selected
        config.hook.pytest_deselected(items=group.deselected)

        self.writer.line(
            self.writer.markup(
                f"\n\n[pytest-split] Running group {group_idx}/{splits} (estimated duration: {group.duration:.2f}s)\n"
            )
        )
        return None


def split_tests(splits: int, items: "List[nodes.Item]", durations: "Dict[str, float]") -> "List[test_group]":
    """
    Split tests into groups by runtime.
    Assigns the test with the largest runtime to the test with the smallest
    duration sum.

    :param splits: How many groups we're splitting in.
    :param group: Which group this run represents.
    :param items: Test items passed down by Pytest.
    :param durations: Our cached test runtimes.
    :return:
        List of groups
    """
    test_ids = [item.nodeid for item in items]
    durations = {k: v for k, v in durations.items() if k in test_ids}

    if durations:
        # Filtering down durations to relevant ones ensures the avg isn't skewed by irrelevant data
        avg_duration_per_test = sum(durations.values()) / len(durations)
    else:
        # If there are no durations, give every test the same arbitrary value
        avg_duration_per_test = 1

    selected: "List[List[nodes.Item]]" = [[] for i in range(splits)]
    deselected: "List[List[nodes.Item]]" = [[] for i in range(splits)]
    duration: "List[float]" = [0 for i in range(splits)]

    # create a heap of the form (summed_durations, group_index)
    heap: "List[Tuple[float, int]]" = [(0, i) for i in range(splits)]
    heapq.heapify(heap)
    for item in items:
        item_duration = durations.get(item.nodeid, avg_duration_per_test)

        # get group with smallest sum
        summed_durations, group_idx = heapq.heappop(heap)
        new_group_durations = summed_durations + item_duration

        # store assignment
        selected[group_idx].append(item)
        duration[group_idx] = new_group_durations
        for i in range(splits):
            if i != group_idx:
                deselected[i].append(item)

        # store new duration - in case of ties it sorts by the group_idx
        heapq.heappush(heap, (new_group_durations, group_idx))

    return [test_group(selected=selected[i], deselected=deselected[i], duration=duration[i]) for i in range(splits)]


class PytestSplitCachePlugin(Base):
    """
    The cache plugin writes durations to our durations file.
    """

    def pytest_sessionfinish(self) -> None:
        """
        Method is called by Pytest after the test-suite has run.
        https://github.com/pytest-dev/pytest/blob/main/src/_pytest/main.py#L308
        """
        terminal_reporter = self.config.pluginmanager.get_plugin("terminalreporter")
        test_durations: "Dict[str, float]" = {}

        for test_reports in terminal_reporter.stats.values():
            for test_report in test_reports:
                if isinstance(test_report, TestReport):

                    # These ifs be removed after this is solved: # https://github.com/spulec/freezegun/issues/286
                    if test_report.duration < 0:
                        continue  # pragma: no cover
                    if (
                        test_report.when in ("teardown", "setup")
                        and test_report.duration > STORE_DURATIONS_SETUP_AND_TEARDOWN_THRESHOLD
                    ):
                        # Ignore not legit teardown durations
                        continue  # pragma: no cover

                    # Add test durations to map
                    if test_report.nodeid not in test_durations:
                        test_durations[test_report.nodeid] = 0
                    test_durations[test_report.nodeid] += test_report.duration

        # Update the full cached-durations object
        for k, v in test_durations.items():
            self.cached_durations[k] = v

        # Save durations
        with open(self.config.option.durations_path, "w") as f:
            json.dump(self.cached_durations, f)

        message = self.writer.markup(
            "\n\n[pytest-split] Stored test durations in {}".format(self.config.option.durations_path)
        )
        self.writer.line(message)
