# Pytest-split

[![Test Workflow](https://github.com/jerry-git/pytest-split/actions/workflows/test.yml/badge.svg?branch=master
)](https://github.com/jerry-git/pytest-split/actions/workflows/test.yml?query=branch%3Amaster)
[![PyPI version](https://badge.fury.io/py/pytest-split.svg)](https://pypi.python.org/pypi/pytest-split/)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/pytest-split.svg)](https://pypi.python.org/pypi/pytest-split/)

Pytest plugin which splits the test suite to equally sized "sub suites" based on test execution time.

## Motivation
* Splitting the test suite is a prerequisite for parallelization (who does not want faster CI builds?). It's valuable to have sub suites which execution time is around the same.
* [`pytest-test-groups`](https://pypi.org/project/pytest-test-groups/) is great but it does not take into account the execution time of sub suites which can lead to notably unbalanced execution times between the sub suites.
* [`pytest-xdist`](https://pypi.org/project/pytest-xdist/) is great but it's not suitable for all use cases.
For example, some test suites may be fragile considering the order in which the tests are executed.
This is of course a fundamental problem in the suite itself but sometimes it's not worth the effort to refactor, especially if the suite is huge (and smells a bit like legacy).
Additionally, `pytest-split` may be a better fit in some use cases considering distributed execution.

## Installation
```
pip install pytest-split
```

## Usage
First we have to store test durations from a complete test suite run.
This produces .test_durations file which should be stored in the repo in order to have it available during future test runs.
The file path is configurable via `--durations-path` CLI option.
```
pytest --store-durations
```

Then we can have as many splits as we want:
```
pytest --splits 3 --group 1
pytest --splits 3 --group 2
pytest --splits 3 --group 3
```

Time goes by, new tests are added and old ones are removed/renamed during development. No worries!
`pytest-split` assumes average test execution time (calculated based on the stored information) for every test which does not have duration information stored.
Thus, there's no need to store durations after changing the test suite.
However, when there are major changes in the suite compared to what's stored in .test_durations, it's recommended to update the duration information with `--store-durations` to ensure that the splitting is in balance.

The splitting algorithm can be controlled with the `--splitting-algorithm` CLI option and defaults to `duration_based_chunks`. For more information about the different algorithms and their tradeoffs, please see the section below.

### CLI commands
#### slowest-tests
Lists the slowest tests based on the information stored in the test durations file. See `slowest-tests help` for more
 information.

## Interactions with other pytest plugins
* [`pytest-random-order`](https://github.com/jbasko/pytest-random-order): ⚠️ The **default settings** of that plugin (setting only `--random-order` to activate it) are **incompatible** with `pytest-split`. Test selection in the groups happens after randomization, potentially causing some tests to be selected in several groups and others not at all. Instead, a global random seed needs to be computed before running the tests (for example using `$RANDOM` from the shell) and that single seed then needs to be used for all groups by setting the `--random-order-seed` option.

## Splitting algorithms
The plugin supports multiple algorithms to split tests into groups.
Each algorithm makes different tradeoffs, but generally `least_duration` should give more balanced groups.

| Algorithm      | Maintains Absolute Order | Maintains Relative Order | Split Quality |
|----------------|--------------------------|--------------------------|---------------|
| duration_based_chunks       | :heavy_check_mark:       | :heavy_check_mark:       | Good          |
| least_duration | :heavy_multiplication_x: | :heavy_check_mark:       | Better        |

Explanation of the terms in the table:
* Absolute Order: whether each group contains all tests between first and last element in the same order as the original list of tests
* Relative Order: whether each test in each group has the same relative order to its neighbours in the group as in the original list of tests

The `duration_based_chunks` algorithm aims to find optimal boundaries for the list of tests and every test group contains all tests between the start and end bounary.
The `least_duration` algorithm walks the list of tests and assigns each test to the group with the smallest current duration.


[**Demo with GitHub Actions**](https://github.com/jerry-git/pytest-split-gh-actions-demo)
