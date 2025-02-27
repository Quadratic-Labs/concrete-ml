"""PyTest configuration file."""
import json
import random
import re
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy
import pytest
import torch
from concrete.fhe import Graph as CNPGraph
from concrete.fhe.compilation import Circuit, Configuration
from concrete.fhe.mlir.utils import MAXIMUM_TLU_BIT_WIDTH
from sklearn.datasets import make_classification, make_regression

from concrete.ml.common.utils import (
    SUPPORTED_FLOAT_TYPES,
    all_values_are_floats,
    is_brevitas_model,
    is_classifier_or_partial_classifier,
    is_model_class_in_a_list,
    is_regressor_or_partial_regressor,
    to_tuple,
)
from concrete.ml.quantization.quantized_module import QuantizedModule
from concrete.ml.sklearn import (
    GammaRegressor,
    PoissonRegressor,
    TweedieRegressor,
    get_sklearn_neural_net_models,
)
from concrete.ml.sklearn.base import (
    BaseTreeEstimatorMixin,
    QuantizedTorchEstimatorMixin,
    SklearnLinearModelMixin,
)


def pytest_addoption(parser):
    """Options for pytest."""

    parser.addoption(
        "--global-coverage-infos-json",
        action="store",
        default=None,
        type=str,
        help="To dump pytest-cov term report to a text file.",
    )

    parser.addoption(
        "--forcing_random_seed",
        action="store",
        default=None,
        type=int,
        help="To force the seed of each and every unit test, to be able to "
        "reproduce a particular issue.",
    )

    parser.addoption(
        "--weekly",
        action="store_true",
        help="To do longer tests.",
    )


# This is only for doctests where we currently cannot make use of fixtures
original_compilation_config_init = Configuration.__init__


def monkeypatched_compilation_configuration_init_for_codeblocks(
    self: Configuration, *args, **kwargs
):
    """Monkeypatched compilation configuration init for codeblocks tests."""
    original_compilation_config_init(self, *args, **kwargs)
    self.dump_artifacts_on_unexpected_failures = False
    self.enable_unsafe_features = True  # This is for our tests only, never use that in prod
    self.treat_warnings_as_errors = True
    self.use_insecure_key_cache = True  # This is for our tests only, never use that in prod
    self.insecure_key_cache_location = "ConcreteNumpyKeyCache"


def pytest_sessionstart(session: pytest.Session):
    """Handle codeblocks Configuration if needed."""
    if session.config.getoption("--codeblocks", default=False):
        # setattr to avoid mypy complaining
        # Disable the flake8 bug bear warning for the mypy fix
        setattr(  # noqa: B010
            Configuration,
            "__init__",
            monkeypatched_compilation_configuration_init_for_codeblocks,
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus):  # pylint: disable=unused-argument
    """Pytest callback when testing ends."""
    # Hacked together from the source code, they don't have an option to export to file and it's too
    # much work to get a PR in for such a little thing
    # https://github.com/pytest-dev/pytest-cov/blob/
    # ec344d8adf2d78238d8f07cb20ed2463d7536970/src/pytest_cov/plugin.py#L329
    if session.config.pluginmanager.hasplugin("_cov"):
        global_coverage_file = session.config.getoption(
            "--global-coverage-infos-json", default=None
        )
        if global_coverage_file is not None:
            cov_plugin = session.config.pluginmanager.getplugin("_cov")
            coverage_txt = cov_plugin.cov_report.getvalue()
            coverage_status = 0
            if (
                cov_plugin.options.cov_fail_under is not None
                and cov_plugin.options.cov_fail_under > 0
            ):
                failed = cov_plugin.cov_total < cov_plugin.options.cov_fail_under
                # If failed is False coverage_status is 0, if True it's 1
                coverage_status = int(failed)
            global_coverage_file_path = Path(global_coverage_file).resolve()
            with open(global_coverage_file_path, "w", encoding="utf-8") as f:
                json.dump({"exit_code": coverage_status, "content": coverage_txt}, f)


@pytest.fixture
def default_configuration():
    """Return the default test compilation configuration."""

    return Configuration(
        dump_artifacts_on_unexpected_failures=False,
        enable_unsafe_features=True,  # This is for our tests only, never use that in prod
        use_insecure_key_cache=True,  # This is for our tests only, never use that in prod
        insecure_key_cache_location="ConcreteNumpyKeyCache",
        jit=True,
    )


@pytest.fixture
def default_configuration_no_jit():
    """Return the default test compilation configuration."""

    return Configuration(
        dump_artifacts_on_unexpected_failures=False,
        enable_unsafe_features=True,  # This is for our tests only, never use that in prod
        use_insecure_key_cache=True,  # This is for our tests only, never use that in prod
        insecure_key_cache_location="ConcreteNumpyKeyCache",
        jit=False,
    )


REMOVE_COLOR_CODES_RE = re.compile(r"\x1b[^m]*m")


@pytest.fixture
def remove_color_codes():
    """Return the re object to remove color codes."""
    return lambda x: REMOVE_COLOR_CODES_RE.sub("", x)


def function_to_seed_torch(seed):
    """Seed torch, for determinism."""

    # Seed torch with something which is seed by pytest-randomly
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


@pytest.fixture(autouse=True)
def autoseeding_of_everything(record_property, request):
    """Seed everything we can, for determinism."""
    main_seed = request.config.getoption("--forcing_random_seed", default=None)

    if main_seed is None:
        main_seed = random.randint(0, 2**64 - 1)

    seed = main_seed
    record_property("main seed", main_seed)

    # Python
    random.seed(seed)
    print("\nForcing seed to random.seed to ", seed)
    print(
        f"\nRelaunch the tests with --forcing_random_seed {seed} "
        + "--randomly-dont-reset-seed to reproduce. Remark that adding --randomly-seed=... "
        + "is needed when the testcase uses randoms in pytest parameters"
    )
    print(
        "Remark that potentially, any option used in the pytest call may have an impact so in "
        + "case of problem to reproduce, you may want to have a look to `make pytest` options"
    )

    # Numpy
    seed += 1
    numpy.random.seed(seed % 2**32)

    # Seed torch
    seed += 1
    function_to_seed_torch(seed)
    return {"main seed": main_seed}


@pytest.fixture
def is_weekly_option(request):
    """Say if we are in --weekly configuration."""
    is_weekly = request.config.getoption("--weekly")
    return is_weekly


# Method is not ideal as some MLIR can contain TLUs but not the associated graph
# FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2381
def check_graph_input_has_no_tlu_impl(graph: CNPGraph):
    """Check that the graph's input node does not contain a TLU."""
    succ = list(graph.graph.successors(graph.input_nodes[0]))
    if any(s.converted_to_table_lookup for s in succ):
        raise AssertionError(f"Graph contains a TLU on an input node: {str(graph.format())}")


# Method is not ideal as some MLIR can contain TLUs but not the associated graph
# FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2381
def check_graph_output_has_no_tlu_impl(graph: CNPGraph):
    """Check that the graph's output node does not contain a TLU."""
    if graph.output_nodes[0].converted_to_table_lookup:
        raise AssertionError(f"Graph output is produced by a TLU: {str(graph.format())}")


# Method is not ideal as some MLIR can contain TLUs but not the associated graph
# FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2381
def check_graph_has_no_input_output_tlu_impl(graph: CNPGraph):
    """Check that the graph's input and output nodes do not contain a TLU."""
    check_graph_input_has_no_tlu_impl(graph)
    check_graph_output_has_no_tlu_impl(graph)


# To update when the feature becomes available in CN
# FIXME: https://github.com/zama-ai/concrete-numpy-internal/issues/1714
def check_circuit_has_no_tlu_impl(circuit: Circuit):
    """Check a circuit has no TLU."""
    if "apply_" in circuit.mlir and "_lookup_table" in circuit.mlir:
        raise AssertionError("The circuit contains at least one TLU")


def check_circuit_precision_impl(circuit: Circuit):
    """Check a circuit doesn't need too much precision."""
    circuit_precision = circuit.graph.maximum_integer_bit_width()
    if circuit_precision > MAXIMUM_TLU_BIT_WIDTH:
        raise AssertionError(
            f"The circuit's precision is expected to be less than {MAXIMUM_TLU_BIT_WIDTH}. "
            f"Got {circuit_precision}."
        )


@pytest.fixture
def check_graph_input_has_no_tlu():
    """Check a circuit has no TLU on input."""
    return check_graph_input_has_no_tlu_impl


@pytest.fixture
def check_graph_output_has_no_tlu():
    """Check a circuit has no TLU on output."""
    return check_graph_output_has_no_tlu_impl


@pytest.fixture
def check_graph_has_no_input_output_tlu():
    """Check a circuit has no TLU on input or output."""
    return check_graph_has_no_input_output_tlu_impl


@pytest.fixture
def check_circuit_has_no_tlu():
    """Check a circuit has no TLU."""
    return check_circuit_has_no_tlu_impl


@pytest.fixture
def check_circuit_precision():
    """Check that the circuit is valid."""
    return check_circuit_precision_impl


def check_array_equality_impl(actual: Any, expected: Any, verbose: bool = True):
    """Assert that `actual` is equal to `expected`."""

    assert numpy.array_equal(actual, expected), (
        ""
        if not verbose
        else f"""

Expected Output
===============
{expected}

Actual Output
=============
{actual}

        """
    )


@pytest.fixture
def check_array_equality():
    """Fixture to check array equality."""

    return check_array_equality_impl


@pytest.fixture
def check_float_arrays_equal():
    """Fixture to check if two float arrays are equal with epsilon precision tolerance."""

    def check_float_arrays_equal_impl(a, b):
        assert numpy.all(numpy.isclose(a, b, rtol=0, atol=0.001))

    return check_float_arrays_equal_impl


@pytest.fixture
def check_r2_score():
    """Fixture to check r2 score."""

    def check_r2_score_impl(expected, actual, acceptance_score=0.99):
        expected = expected.ravel()
        actual = actual.ravel()
        mean_expected = numpy.mean(expected)
        deltas_expected = expected - mean_expected
        deltas_actual = actual - expected
        r2_den = numpy.sum(deltas_expected**2)
        r2_num = numpy.sum(deltas_actual**2)

        # If the values are really close, we consider the test passes
        is_close = numpy.allclose(expected, actual, atol=1e-4, rtol=0)
        if is_close:
            return

        # If the variance of the target values is very low, fix the max allowed for residuals
        # to a known value
        r2_den = max(r2_den, 1e-5)

        r_square = 1 - r2_num / r2_den
        assert (
            r_square >= acceptance_score
        ), f"r2 score of {numpy.round(r_square, 4)} is not high enough."

    return check_r2_score_impl


@pytest.fixture
def check_accuracy():
    """Fixture to check the accuracy."""

    def check_accuracy_impl(expected, actual, threshold=0.9):
        accuracy = numpy.mean(expected == actual)
        assert accuracy >= threshold, f"Accuracy of {accuracy} is not high enough ({threshold})."

    return check_accuracy_impl


@pytest.fixture
def load_data():
    """Fixture for generating random regression or classification problem."""

    def load_data_impl(
        model_class: Callable,
        *args,
        random_state: Optional[int] = None,
        **kwargs,
    ):
        """Generate a random regression or classification problem.

        Sklearn's make_regression() method generates a random regression problem without any domain
        restrictions. However, some models can only handle non negative or (strictly) positive
        target values. This function therefore adapts it in order to make it work for any tested
        regressors.

        For classifier, Sklearn's make_classification() method is directly called.

        Args:
            model_class (Callable): The Concrete ML model class to generate the data for.
            *args: Positional arguments to consider for generating the data.
            random_state (int): Determines random number generation for data-set creation.
            **kwargs: Keyword arguments to consider for generating the data.
        """
        # Create a random_state value in order to seed the data generation functions. This enables
        # all tests that use this fixture to be deterministic and thus reproducible.
        random_state = numpy.random.randint(0, 2**15) if random_state is None else random_state

        # If the dataset should be generated for a classification problem.
        if is_classifier_or_partial_classifier(model_class) or is_brevitas_model(model_class):
            generated_classifier = list(
                make_classification(*args, **kwargs, random_state=random_state)
            )

            # Cast inputs to float32 as Skorch QNNs don't handle float64 values
            if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
                generated_classifier[0] = generated_classifier[0].astype(numpy.float32)

            return tuple(generated_classifier)

        # If the dataset should be generated for a regression problem.
        if is_regressor_or_partial_regressor(model_class):
            generated_regression = list(make_regression(*args, **kwargs, random_state=random_state))

            # Generalized Linear Models can only handle positive target values,
            # often strictly positive.
            if is_model_class_in_a_list(
                model_class, [GammaRegressor, PoissonRegressor, TweedieRegressor]
            ):
                generated_regression[1] = numpy.abs(generated_regression[1]) + 1

            # If the model is a neural network and if the dataset only contains a single target
            # (e.g. of shape (n,)), reshape the target array (e.g. to shape (n,1))
            if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
                if len(generated_regression[1].shape) == 1:
                    generated_regression[1] = generated_regression[1].reshape(-1, 1)

                # Cast inputs and targets to float32 as Skorch QNNs don't handle float64 values
                generated_regression[0] = generated_regression[0].astype(numpy.float32)
                generated_regression[1] = generated_regression[1].astype(numpy.float32)

            return tuple(generated_regression)

        raise ValueError(
            "Model class type is unsupported. Expected a Concrete ML regressor or classifier, or "
            f"a functool.partial version of it, but got {model_class}."
        )

    return load_data_impl


@pytest.fixture
def check_is_good_execution_for_cml_vs_circuit():
    """Compare quantized module or built-in inference vs Concrete circuit."""

    def check_is_good_execution_for_cml_vs_circuit_impl(
        inputs: Union[tuple, numpy.ndarray],
        model: Union[Callable, QuantizedModule, QuantizedTorchEstimatorMixin],
        simulate: bool,
        n_allowed_runs: int = 5,
    ):
        """Check that a model or a quantized module give the same output as the circuit.

        Args:
            inputs (tuple, numpy.ndarray): inputs for the model.
            model (Callable, QuantizedModule, QuantizedTorchEstimatorMixin): either the
                Concrete ML sklearn built-in model or a quantized module.
            simulate (bool): whether to run the execution in FHE or in simulated mode.
            n_allowed_runs (int): in case of FHE execution randomness can make the output slightly
                different this allows to run the evaluation multiple times
        """

        inputs = to_tuple(inputs)

        # Make sure that the inputs are floating points
        assert all_values_are_floats(*inputs), (
            f"Input values are expected to be floating points of dtype {SUPPORTED_FLOAT_TYPES}. "
            "Do not quantize the inputs manually as it is handled within this method."
        )

        fhe_mode = "simulate" if simulate else "execute"

        for _ in range(n_allowed_runs):
            # Check if model is QuantizedModule
            if isinstance(model, QuantizedModule):
                results_cnp_circuit = model.forward(*inputs, fhe=fhe_mode)
                results_model = model.forward(*inputs, fhe="disable")

            else:
                assert isinstance(
                    model,
                    (QuantizedTorchEstimatorMixin, BaseTreeEstimatorMixin, SklearnLinearModelMixin),
                )

                if model._is_a_public_cml_model:  # pylint: disable=protected-access
                    # Only check probabilities for classifiers as we only want to check that the
                    # circuit's outputs (after de-quantization) are correct. We thus want to avoid
                    # as much post-processing steps in the clear (that could lead to more flaky
                    # tests), especially since these results are tested in other tests such as the
                    # `check_subfunctions_in_fhe`
                    if is_classifier_or_partial_classifier(model):
                        results_cnp_circuit = model.predict_proba(*inputs, fhe=fhe_mode)
                        results_model = model.predict_proba(*inputs, fhe="disable")

                    else:
                        results_cnp_circuit = model.predict(*inputs, fhe=fhe_mode)
                        results_model = model.predict(*inputs, fhe="disable")

                else:
                    raise ValueError(
                        "numpy_function should be a built-in concrete sklearn model or "
                        "a QuantizedModule object."
                    )

            # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2806
            # fp64 comparisons do not pass the numpy.array_equal while the quantized
            # int64 values do.
            if numpy.isclose(results_cnp_circuit, results_model).all():
                return

        raise RuntimeError(
            f"Mismatch between circuit results:\n{results_cnp_circuit}\n"
            f"and model function results:\n{results_model}"
        )

    return check_is_good_execution_for_cml_vs_circuit_impl
