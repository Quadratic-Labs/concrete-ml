"""Tests for the sklearn models.

Generic tests test:
  - model (with n_bits)
  - FHE simulation or not
  - fit
  - double fit
  - compile
  - grid search
  - hyper parameters
  - offset
  - correctness (with accuracy and r2) of Concrete ML vs scikit-learn in clear
  - correctness tests with fhe = "disable", "simulate" and "execute", depending on
  limits (see N_BITS_THRESHOLD* constants) which are either due to execution time or limits of
  the compiler or minimal number of bits for precise computations
  - fit_benchmark
  - r2 score / accuracies
  - pandas
  - pipeline
  - calls to predict_proba
  - calls to decision_function

Are currently missing
  - check of predict_proba
  - check of decision_function

More information in https://github.com/zama-ai/concrete-ml-internal/issues/2682
"""

# pylint: disable=too-many-lines
import json
import tempfile
import warnings
from typing import Any, Dict, List

import numpy
import pandas
import pytest
import torch
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import make_scorer, matthews_corrcoef, mean_squared_error
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn

from concrete.ml.common.serialization.dumpers import dump, dumps
from concrete.ml.common.serialization.loaders import load, loads
from concrete.ml.common.utils import (
    get_model_class,
    get_model_name,
    is_classifier_or_partial_classifier,
    is_model_class_in_a_list,
    is_regressor_or_partial_regressor,
)
from concrete.ml.pytest.utils import (
    _classifiers_and_datasets,
    instantiate_model_generic,
    sklearn_models_and_datasets,
)
from concrete.ml.sklearn import (
    get_sklearn_linear_models,
    get_sklearn_neural_net_models,
    get_sklearn_tree_models,
)

# Allow multiple runs in FHE to make sure we always have the correct output
N_ALLOWED_FHE_RUN = 5

# If n_bits >= N_BITS_THRESHOLD_FOR_SKLEARN_CORRECTNESS_TESTS, we check correctness against
# scikit-learn in the clear, via check_correctness_with_sklearn function. This is because we need
# sufficiently number of bits for precision
N_BITS_THRESHOLD_FOR_SKLEARN_CORRECTNESS_TESTS = 26

# We check correctness with check_is_good_execution_for_cml_vs_circuit or predict in
# fhe="disable" only if n_bits >= N_BITS_THRESHOLD_FOR_PREDICT_CORRECTNESS_TESTS. This is
# because we need sufficiently number of bits for precision
N_BITS_THRESHOLD_FOR_PREDICT_CORRECTNESS_TESTS = 6

# We never do checks with check_is_good_execution_for_cml_vs_circuit if
# n_bits >= N_BITS_THRESHOLD_TO_FORCE_EXECUTION_NOT_IN_FHE. This is because computations are very
# slow
N_BITS_THRESHOLD_TO_FORCE_EXECUTION_NOT_IN_FHE = 17

assert (
    N_BITS_THRESHOLD_FOR_PREDICT_CORRECTNESS_TESTS <= N_BITS_THRESHOLD_TO_FORCE_EXECUTION_NOT_IN_FHE
)

# If n_bits >= N_BITS_THRESHOLD_FOR_SKLEARN_EQUIVALENCE_TESTS, we check that the two models
# returned by fit_benchmark (the CML model and the scikit-learn model) are equivalent
N_BITS_THRESHOLD_FOR_SKLEARN_EQUIVALENCE_TESTS = 16

# There is a risk that no cryptographic parameters are available for high precision linear
# models. N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS makes sure we do not create linear models
# that do not have cryptographic parameters.
N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS = 11

# n_bits that we test, either in regular builds or just in weekly builds. 6 is to do tests in
# FHE which are not too long (relation with N_BITS_THRESHOLD_FOR_PREDICT_CORRECTNESS_TESTS and
# N_BITS_THRESHOLD_TO_FORCE_EXECUTION_NOT_IN_FHE). 26 is in relation with
# N_BITS_THRESHOLD_FOR_SKLEARN_CORRECTNESS_TESTS, to do tests with check_correctness_with_sklearn
N_BITS_REGULAR_BUILDS = [6, 26]
N_BITS_WEEKLY_ONLY_BUILDS = [2, 8, 16]

# Circuit with 9 bits up to 16 bits are currently using the CRT circuit. We do not test them here
# as they take a bit more time than non-CRT based FHE circuit.
# N_BITS_THRESHOLD_FOR_CRT_FHE_CIRCUITS defines the threshold for which the circuit will be using
# the CRT.
N_BITS_THRESHOLD_FOR_CRT_FHE_CIRCUITS = 9


def get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option):
    """Prepare the the (x, y) dataset."""

    if not is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
        if n_bits in N_BITS_WEEKLY_ONLY_BUILDS and not is_weekly_option:
            pytest.skip("Skipping some tests in non-weekly builds, except for linear models")

    # Get the dataset. The data generation is seeded in load_data.
    x, y = load_data(model_class, **parameters)

    return x, y


def preamble(model_class, parameters, n_bits, load_data, is_weekly_option):
    """Prepare the fitted model, and the (x, y) dataset."""

    if not is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
        if n_bits in N_BITS_WEEKLY_ONLY_BUILDS and not is_weekly_option:
            pytest.skip("Skipping some tests in non-weekly builds")

    # Get the dataset. The data generation is seeded in load_data.
    model = instantiate_model_generic(model_class, n_bits=n_bits)
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(x, y)

    return model, x


def check_correctness_with_sklearn(
    model_class,
    x,
    y,
    check_r2_score,
    check_accuracy,
    hyper_parameters_including_n_bits,
    fhe="disable",
):
    """Check that Concrete ML and scikit-learn models are 'equivalent'."""
    assert "n_bits" in hyper_parameters_including_n_bits

    model = instantiate_model_generic(model_class, **hyper_parameters_including_n_bits)

    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model, sklearn_model = model.fit_benchmark(x, y)

    y_pred = model.predict(x)

    y_pred_sklearn = sklearn_model.predict(x)
    y_pred_cml = model.predict(x, fhe=fhe)

    # Check that the output shapes are correct
    assert y_pred.shape == y_pred_cml.shape, "Outputs have different shapes"

    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2604
    # Generic tests look to show issues in accuracy / R2 score, even for high n_bits

    # For regressions
    acceptance_r2score_dic = {
        "TweedieRegressor": 0.9,
        "GammaRegressor": 0.9,
        "LinearRegression": 0.9,
        "LinearSVR": 0.9,
        "PoissonRegressor": 0.9,
        "Lasso": 0.9,
        "Ridge": 0.9,
        "ElasticNet": 0.9,
        "XGBRegressor": -0.2,
        "NeuralNetRegressor": -10,
    }

    # For classifiers
    threshold_accuracy_dic = {
        "LogisticRegression": 0.9,
        "LinearSVC": 0.9,
        "XGBClassifier": 0.7,
        "RandomForestClassifier": 0.8,
        "NeuralNetClassifier": 0.7,
    }

    model_name = get_model_name(model_class)
    acceptance_r2score = acceptance_r2score_dic.get(model_name, 0.9)
    threshold_accuracy = threshold_accuracy_dic.get(model_name, 0.9)

    # If the model is a classifier, check that accuracies are similar
    if is_classifier_or_partial_classifier(model):
        check_accuracy(y_pred_sklearn, y_pred_cml, threshold=threshold_accuracy)

    # If the model is a regressor, check that R2 scores are similar
    else:
        assert is_regressor_or_partial_regressor(
            model
        ), "not a regressor, not a classifier, really?"
        check_r2_score(y_pred_sklearn, y_pred_cml, acceptance_score=acceptance_r2score)


def check_double_fit(model_class, n_bits, x, y):
    """Check double fit."""
    model = instantiate_model_generic(model_class, n_bits=n_bits)

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)

        # First fit: here, we really need to fit, we can't reuse an already fitted model
        if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):

            # Generate a seed for the PyTorch RNG
            main_seed = numpy.random.randint(0, 2**63)
            torch.manual_seed(main_seed)

        model.fit(x, y)
        y_pred_one = model.predict(x)

        # Second fit: here, we really need to fit, we can't reuse an already fitted model
        if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
            torch.manual_seed(main_seed)

        model.fit(x, y)
        y_pred_two = model.predict(x)

    assert numpy.array_equal(y_pred_one, y_pred_two)


def check_serialization(model, x):
    """Check serialization."""

    model_class = get_model_class(model)

    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/3134
    # Waiting that QNN are serialized
    if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
        pytest.skip(f"Serialization not supported yet for {model_class}")

    check_serialization_dump_load(model, x)
    check_serialization_dumps_loads(model, x)


def check_serialization_dump_load(model, x):
    """Check that a model can be serialized two times using dump/load methods."""

    model_class = get_model_class(model)

    with tempfile.TemporaryFile("w+") as temp_dump:
        # Disable mypy
        for (dump_method, load_method) in [
            (dump, load),
            (model_class.dump, model_class.load),
        ]:
            # Dump the model into the file
            temp_dump.seek(0)
            temp_dump.truncate(0)
            dump_method(model, file=temp_dump)

            # Load the model from the file as a dict using json
            temp_dump.seek(0)
            serialized_model_dict: Dict = json.load(temp_dump)

            # Load the model from the file using Concrete ML's method
            temp_dump.seek(0)
            loaded_model = load_method(file=temp_dump)

            # Dump the loaded model into the file using Concrete ML's method
            temp_dump.seek(0)
            temp_dump.truncate(0)
            dump_method(loaded_model, file=temp_dump)

            # Load the model from the file again as a dict using json
            temp_dump.seek(0)
            re_serialized_model_dict: Dict = json.load(temp_dump)

            # Check that the dictionaries are identical (except for sklearn_model attribute, as
            # it is serialized using the pickle library, which does not handle double serialization)
            del serialized_model_dict["sklearn_model"]
            del re_serialized_model_dict["sklearn_model"]
            assert serialized_model_dict == re_serialized_model_dict

            # Check that the predictions made by both model are identical
            y_pred_model = model.predict(x)
            y_pred_loaded_model = loaded_model.predict(x)
            assert numpy.array_equal(y_pred_model, y_pred_loaded_model)

            # Check that the predictions made by both Scikit-Learn model are identical
            y_pred_sklearn_model = model.sklearn_model.predict(x)
            y_pred_loaded_sklearn_model = loaded_model.sklearn_model.predict(x)
            assert numpy.array_equal(y_pred_sklearn_model, y_pred_loaded_sklearn_model)


def check_serialization_dumps_loads(model, x):
    """Check that a model can be serialized two times using dumps/loads methods."""

    model_class = get_model_class(model)

    for (dumps_method, loads_method) in [
        (dumps, loads),
        (model_class.dumps, model_class.loads),
    ]:
        # Dump the model into a string
        serialized_model = dumps_method(model)

        # Load the model from the string
        loaded_model = loads_method(serialized_model)

        # Dump the model into a string again
        re_serialized_model: str = dumps_method(loaded_model)

        # Load both strings using json
        serialized_model_dict: Dict = json.loads(serialized_model)
        re_serialized_model_dict: Dict = json.loads(re_serialized_model)

        # Check that the dictionaries are identical (except for sklearn_model attribute, as
        # it is serialized using the pickle library, which does not handle double serialization)
        del serialized_model_dict["sklearn_model"]
        del re_serialized_model_dict["sklearn_model"]
        assert serialized_model_dict == re_serialized_model_dict

        # Check that the predictions made by both model are identical
        y_pred_model = model.predict(x)
        y_pred_loaded_model = loaded_model.predict(x)
        assert numpy.array_equal(y_pred_model, y_pred_loaded_model)

        # Check that the predictions made by both Scikit-Learn model are identical
        y_pred_sklearn_model = model.sklearn_model.predict(x)
        y_pred_loaded_sklearn_model = loaded_model.sklearn_model.predict(x)
        assert numpy.array_equal(y_pred_sklearn_model, y_pred_loaded_sklearn_model)


def check_offset(model_class, n_bits, x, y):
    """Check offset."""
    model = instantiate_model_generic(model_class, n_bits=n_bits)

    # Offsets are not supported by XGBoost
    if is_model_class_in_a_list(model_class, get_sklearn_tree_models(str_in_class_name="XGB")):
        # No pytest.skip, since it is not a bug but something which is inherent to XGB
        return

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)

        # Add the offset: here, we really need to fit, we can't reuse an already fitted model
        y += 3
        model.fit(x, y)
        model.predict(x[:1])

        # Another offset: here, we really need to fit, we can't reuse an already fitted model
        y -= 2
        model.fit(x, y)


def check_subfunctions(fitted_model, model_class, x):
    """Check subfunctions."""

    fitted_model.predict(x[:1])

    # Skorch provides a predict_proba method for neural network regressors while Scikit-Learn does
    # not. We decided to follow Scikit-Learn's API as we build most of our tools on this library.
    # However, our models are still directly inheriting from Skorch's classes, which makes this
    # method accessible by anyone, without having any FHE implementation. As this could create some
    # confusion, a NotImplementedError is raised. This issue could be fixed by making these classes
    # not inherit from Skorch.
    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/3373
    if get_model_name(fitted_model) == "NeuralNetRegressor":
        with pytest.raises(
            NotImplementedError,
            match=(
                "The `predict_proba` method is not implemented for neural network regressors. "
                "Please call `predict` instead."
            ),
        ):
            fitted_model.predict_proba(x)

    if is_classifier_or_partial_classifier(model_class):

        fitted_model.predict_proba(x)

        # Only linear classifiers have a decision function method
        if is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
            fitted_model.decision_function(x)


def check_subfunctions_in_fhe(model, fhe_circuit, x):
    """Check subfunctions in FHE: calls and correctness."""

    # Generate the keys
    fhe_circuit.keygen()

    y_pred_fhe = []

    for _ in range(N_ALLOWED_FHE_RUN):
        for f_input in x:
            # Quantize an input (float)
            q_input = model.quantize_input(f_input.reshape(1, -1))

            # Encrypt the input
            q_input_enc = fhe_circuit.encrypt(q_input)

            # Execute the linear product in FHE
            q_y_enc = fhe_circuit.run(q_input_enc)

            # Decrypt the result (integer)
            q_y = fhe_circuit.decrypt(q_y_enc)

            # Dequantize the result
            y = model.dequantize_output(q_y)

            # Apply either the sigmoid if it is a binary classification task,
            # which is the case in this example, or a softmax function in order
            # to get the probabilities (in the clear)
            y_proba = model.post_processing(y)

            # Apply the argmax to get the class predictions (in the clear)
            if is_classifier_or_partial_classifier(model):
                y_class = numpy.argmax(y_proba, axis=-1)
                y_pred_fhe += list(y_class)
            else:
                y_pred_fhe += list(y_proba)

        # Compare with the FHE simulation mode
        y_pred_expected_in_simulation = model.predict(x, fhe="simulate")
        if numpy.isclose(numpy.array(y_pred_fhe), y_pred_expected_in_simulation).all():
            break

    assert numpy.isclose(numpy.array(y_pred_fhe), y_pred_expected_in_simulation).all(), (
        "computations are not the same between individual functions (in FHE) "
        "and predict function (in FHE simulation mode)"
    )


def check_input_support(model_class, n_bits, default_configuration, x, y, input_type):
    """Test all models with Pandas, List or Torch inputs."""

    def cast_input(x, y, input_type):
        "Convert x and y either in Pandas, List, Numpy or Torch type."

        assert input_type in ["pandas", "torch", "list", "numpy"], "Not a valid type casting"

        if input_type.lower() == "pandas":
            # Turn into Pandas
            x = pandas.DataFrame(x)
            y = pandas.Series(y) if y.ndim == 1 else pandas.DataFrame(y)
        elif input_type.lower() == "torch":
            # Turn into Torch
            x = torch.tensor(x)
            y = torch.tensor(y)
        elif input_type.lower() == "list":
            # Turn into List
            x = x.tolist()
            y = y.tolist()
        elif input_type.lower() == "numpy":
            assert isinstance(x, numpy.ndarray), f"Wrong type {type(x)}"
            assert isinstance(y, numpy.ndarray), f"Wrong type {type(y)}"
        return x, y

    model = instantiate_model_generic(model_class, n_bits=n_bits)
    x, y = cast_input(x, y, input_type=input_type)

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(x, y)

    # Make sure `predict` is working when FHE is disabled
    model.predict(x)

    # Similarly, we test `predict_proba` for classifiers
    if is_classifier_or_partial_classifier(model):
        model.predict_proba(x)

    # If n_bits is above N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS, do not compile the model
    # as there won't be any crypto parameters
    if n_bits >= N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS:
        return

    model.compile(x, default_configuration)

    # Make sure `predict` is working when FHE is disabled
    model.predict(x, fhe="simulate")

    # Similarly, we test `predict_proba` for classifiers
    if is_classifier_or_partial_classifier(model):
        model.predict_proba(x, fhe="simulate")


def check_pipeline(model_class, x, y):
    """Check pipeline support."""

    # Pipeline test sometimes fails with RandomForest models. This bug may come from Hummingbird
    # and needs further investigations
    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2779
    if is_model_class_in_a_list(
        model_class, get_sklearn_tree_models(str_in_class_name="RandomForest")
    ):
        pytest.skip("Skipping pipeline test for RF, doesn't work for now")

    hyper_param_combinations = get_hyper_param_combinations(model_class)

    # Prepare the list of all hyper parameters
    hyperparameters_list = [
        {key: value} for key, values in hyper_param_combinations.items() for value in values
    ]

    # Take one of the hyper_parameters randomly (testing everything would be too long)
    if len(hyperparameters_list) == 0:
        hyper_parameters = {}
    else:
        hyper_parameters = hyperparameters_list[numpy.random.randint(0, len(hyperparameters_list))]

    pipe_cv = Pipeline(
        [
            ("pca", PCA(n_components=2, random_state=numpy.random.randint(0, 2**15))),
            ("scaler", StandardScaler()),
            ("model", model_class(**hyper_parameters)),
        ]
    )

    # Do a grid search to find the best hyper-parameters
    if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
        param_grid = {
            "model__module__n_w_bits": [2, 3],
            "model__module__n_a_bits": [2, 3],
        }

    else:
        param_grid = {
            "model__n_bits": [2, 3],
        }

    grid_search = GridSearchCV(pipe_cv, param_grid, error_score="raise", cv=3)

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)

        grid_search.fit(x, y)


def check_grid_search(model_class, x, y):
    """Check grid search."""
    if is_classifier_or_partial_classifier(model_class):
        grid_scorer = make_scorer(matthews_corrcoef, greater_is_better=True)
    else:
        grid_scorer = make_scorer(mean_squared_error, greater_is_better=True)

    if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
        param_grid = {
            "module__n_layers": [2, 3],
            "module__n_hidden_neurons_multiplier": [1],
            "module__activation_function": (nn.ReLU6,),
        }
    elif model_class in get_sklearn_tree_models(str_in_class_name="DecisionTree"):
        param_grid = {
            "n_bits": [20],
        }
    elif model_class in get_sklearn_tree_models():
        param_grid = {
            "n_bits": [20],
            "max_depth": [2],
            "n_estimators": [5, 10],
            "n_jobs": [1],
        }
    else:
        param_grid = {
            "n_bits": [20],
        }

    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)

        _ = GridSearchCV(
            model_class(), param_grid, cv=5, scoring=grid_scorer, error_score="raise", n_jobs=1
        ).fit(x, y)


def check_sklearn_equivalence(model_class, n_bits, x, y, check_accuracy, check_r2_score):
    """Check equivalence between the two models returned by fit_benchmark: the CML model and
    the scikit-learn model."""
    model = instantiate_model_generic(model_class, n_bits=n_bits)

    # The `fit_benchmark` function of QNNs returns a QAT model and a FP32 model that is similar
    # in structure but trained from scratch. Furthermore, the `n_bits` setting
    # of the QNN instantiation in `instantiate_model_generic` takes `n_bits` as
    # a target accumulator and sets 3-b w&a for these tests. Thus it's
    # impossible to reach R-2 of 0.99 when comparing the two NN models returned by `fit_benchmark`
    if is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
        pytest.skip("Skipping sklearn-equivalence test for NN, doesn't work for now")

    # Sometimes, we miss convergence, which is not a problem for our test
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)

        # Random state should be taken from the method parameter
        model, sklearn_model = model.fit_benchmark(x, y)

    # If the model is a classifier
    if is_classifier_or_partial_classifier(model):

        # Check that accuracies are similar
        y_pred_cml = model.predict(x)
        y_pred_sklearn = sklearn_model.predict(x)
        check_accuracy(y_pred_sklearn, y_pred_cml)

        # If the model is a LinearSVC model, compute its predicted confidence score
        # This is done separately as scikit-learn doesn't provide a predict_proba method for
        # LinearSVC models
        if get_model_name(model_class) == "LinearSVC":
            y_pred_cml = model.decision_function(x)
            y_pred_sklearn = sklearn_model.decision_function(x)

        # Else, compute the model's predicted probabilities
        else:
            y_pred_cml = model.predict_proba(x)
            y_pred_sklearn = sklearn_model.predict_proba(x)

    # If the model is a regressor, compute its predictions
    else:
        y_pred_cml = model.predict(x)
        y_pred_sklearn = sklearn_model.predict(x)

    # Check that predictions, probabilities or confidence scores are similar using the R2 score
    check_r2_score(y_pred_sklearn, y_pred_cml)


def check_properties_of_circuit(model_class, fhe_circuit, check_circuit_has_no_tlu):
    """Check some properties of circuit, depending on the model class"""

    if is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
        # Check that no TLUs are found within the MLIR
        check_circuit_has_no_tlu(fhe_circuit)


def get_hyper_param_combinations(model_class):
    """Return the hyper_param_combinations, depending on the model class"""
    hyper_param_combinations: Dict[str, List[Any]]

    if is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
        hyper_param_combinations = {"fit_intercept": [False, True]}
    elif model_class in get_sklearn_tree_models(str_in_class_name="DecisionTree"):
        hyper_param_combinations = {}
    elif model_class in get_sklearn_tree_models(str_in_class_name="RandomForest"):
        hyper_param_combinations = {
            "max_depth": [3, 4, 5, 10],
            "min_samples_split": [2, 3, 4, 5],
            "min_samples_leaf": [1, 2, 3, 4],
            "min_weight_fraction_leaf": [0.0, 0.1, 0.2, 0.3],
            "max_features": ["sqrt", "log2"],
            "max_leaf_nodes": [None, 5, 10, 20],
        }
    elif model_class in get_sklearn_tree_models(str_in_class_name="XGB"):
        hyper_param_combinations = {
            "max_depth": [3, 4, 5, 10],
            "learning_rate": [1, 0.5, 0.1],
            "n_estimators": [1, 50, 100, 1000],
            "tree_method": ["auto", "exact", "approx"],
            "gamma": [0, 0.1, 0.5],
            "min_child_weight": [1, 5, 10],
            "max_delta_step": [0, 0.5, 0.7],
            "subsample": [0.5, 0.9, 1.0],
            "colsample_bytree": [0.5, 0.9, 1.0],
            "colsample_bylevel": [0.5, 0.9, 1.0],
            "colsample_bynode": [0.5, 0.9, 1.0],
            "reg_alpha": [0, 0.1, 0.5],
            "reg_lambda": [0, 0.1, 0.5],
            "scale_pos_weight": [0.5, 0.9, 1.0],
            "importance_type": ["weight", "gain"],
            "base_score": [0.5, None],
        }
    else:

        assert is_model_class_in_a_list(
            model_class, get_sklearn_neural_net_models()
        ), "models are supposed to be tree-based or linear or QNN's"

        hyper_param_combinations = {}

    # Don't put n_bits in hyper_parameters, it comes from the test itself
    assert "n_bits" not in hyper_param_combinations

    return hyper_param_combinations


def check_hyper_parameters(
    model_class,
    n_bits,
    x,
    y,
    test_correctness_in_clear,
    check_r2_score,
    check_accuracy,
):
    """Check hyper parameters."""
    hyper_param_combinations = get_hyper_param_combinations(model_class)

    # Prepare the list of all hyper parameters
    hyperparameters_list = [
        {key: value} for key, values in hyper_param_combinations.items() for value in values
    ]

    for hyper_parameters in hyperparameters_list:

        # Add n_bits
        hyper_parameters["n_bits"] = n_bits

        model = instantiate_model_generic(model_class, **hyper_parameters)

        # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2450
        # does not work for now, issue in HummingBird
        if (
            get_model_name(model_class) == "RandomForestClassifier"
            and hyper_parameters["n_bits"] == 2
        ):
            continue

        # Also fit with these hyper parameters to check it works fine
        with warnings.catch_warnings():
            # Sometimes, we miss convergence, which is not a problem for our test
            warnings.simplefilter("ignore", category=ConvergenceWarning)

            # Here, we really need to fit, to take into account hyper parameters
            model.fit(x, y)

        # Check correctness with sklearn (if we have sufficiently bits of precision)
        if test_correctness_in_clear and n_bits >= N_BITS_THRESHOLD_FOR_SKLEARN_CORRECTNESS_TESTS:
            check_correctness_with_sklearn(
                model_class,
                x,
                y,
                check_r2_score,
                check_accuracy,
                hyper_parameters_including_n_bits=hyper_parameters,
                fhe="disable",
            )


def check_fitted_compiled_error_raises(model_class, n_bits, x, y):
    """Check that methods that require the model to be compiled or fitted raise proper errors."""

    model = instantiate_model_generic(model_class, n_bits=n_bits)

    # Quantizing inputs with an untrained model should not be possible
    with pytest.raises(AttributeError, match=".* model is not fitted.*"):
        model.quantize_input(x)

    # Quantizing outputs with an untrained model should not be possible
    with pytest.raises(AttributeError, match=".* model is not fitted.*"):
        model.dequantize_output(x)

    # Compiling an untrained model should not be possible
    with pytest.raises(AttributeError, match=".* model is not fitted.*"):
        model.compile(x)

    # Predicting in FHE using an untrained model should not be possible
    with pytest.raises(AttributeError, match=".* model is not fitted.*"):
        model.predict(x, fhe="execute")

    # Predicting in clear using an untrained model should not be possible for linear and
    # tree-based models
    if not is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
        with pytest.raises(AttributeError, match=".* model is not fitted.*"):
            model.predict(x)

    if is_classifier_or_partial_classifier(model_class):
        # Predicting probabilities using an untrained linear or tree-based classifier should not
        # be possible
        if not is_model_class_in_a_list(model_class, get_sklearn_neural_net_models()):
            with pytest.raises(AttributeError, match=".* model is not fitted.*"):
                model.predict_proba(x)

        # Predicting probabilities in FHE using an untrained QNN classifier should not be possible
        else:
            with pytest.raises(AttributeError, match=".* model is not fitted.*"):
                model.predict_proba(x, fhe="execute")

        # Computing the decision function using an untrained classifier should not be possible.
        # Note that the `decision_function` method is only available for linear models
        if is_model_class_in_a_list(model_class, get_sklearn_linear_models()):
            with pytest.raises(AttributeError, match=".* model is not fitted.*"):
                model.decision_function(x)

    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(x, y)

    # Predicting in FHE using a trained model that is not compiled should not be possible
    with pytest.raises(AttributeError, match=".* model is not compiled.*"):
        model.predict(x, fhe="execute")

    # Predicting probabilities in FHE using a trained QNN classifier that is not compiled should
    # not be possible
    if is_classifier_or_partial_classifier(model_class) and is_model_class_in_a_list(
        model_class, get_sklearn_neural_net_models()
    ):
        with pytest.raises(AttributeError, match=".* model is not compiled.*"):
            model.predict_proba(x, fhe="execute")


def check_class_mapping(model, x, y):
    """Check that classes with arbitrary labels are handled for all classifiers."""

    # Retrieve the data's target labels
    classes = numpy.unique(y)

    # Make sure these targets are ordered by default
    assert numpy.array_equal(numpy.arange(len(classes)), classes)

    # Fit the model
    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(x, y)

    # Compute the predictions
    y_pred = model.predict(x)

    # Shuffle the initial labels (in place)
    numpy.random.shuffle(classes)

    # Map each targets' label to the the new shuffled ones
    new_y = classes[y]

    # Fit the model using these new targets
    with warnings.catch_warnings():
        # Sometimes, we miss convergence, which is not a problem for our test
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        model.fit(x, new_y)

    # Compute the predictions
    y_pred_shuffled = model.predict(x)

    # Check that the mapping of labels was kept by Concrete ML
    numpy.array_equal(classes[y_pred], y_pred_shuffled)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    [
        n
        for n in N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS
        if n >= N_BITS_THRESHOLD_FOR_SKLEARN_EQUIVALENCE_TESTS
    ],
)
# pylint: disable=too-many-arguments
def test_quantization(
    model_class,
    parameters,
    n_bits,
    load_data,
    check_r2_score,
    check_accuracy,
    is_weekly_option,
    verbose=True,
):
    """Test quantization."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_sklearn_equivalence")

    check_sklearn_equivalence(model_class, n_bits, x, y, check_accuracy, check_r2_score)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    [
        n
        for n in N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS
        if n >= N_BITS_THRESHOLD_FOR_SKLEARN_CORRECTNESS_TESTS
    ],
)
# pylint: disable=too-many-arguments
def test_correctness_with_sklearn(
    model_class,
    parameters,
    n_bits,
    load_data,
    check_r2_score,
    check_accuracy,
    is_weekly_option,
    verbose=True,
):
    """Test that Concrete ML and scikit-learn models are 'equivalent'."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    # Check correctness with sklearn (if we have sufficiently bits of precision)
    if verbose:
        print("Run check_correctness_with_sklearn with fhe='disable'")

    check_correctness_with_sklearn(
        model_class,
        x,
        y,
        check_r2_score,
        check_accuracy,
        hyper_parameters_including_n_bits={"n_bits": n_bits},
        fhe="disable",
    )


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_hyper_parameters(
    model_class,
    parameters,
    n_bits,
    load_data,
    check_r2_score,
    check_accuracy,
    is_weekly_option,
    verbose=True,
):
    """Testing hyper parameters."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_hyper_parameters")

    test_correctness_in_clear = True

    check_hyper_parameters(
        model_class,
        n_bits,
        x,
        y,
        test_correctness_in_clear,
        check_r2_score,
        check_accuracy,
    )


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    [3],
)
# pylint: disable=too-many-arguments
def test_grid_search(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test Grid search."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_grid_search")

    check_grid_search(model_class, x, y)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_serialization(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test Serialization."""
    model, x = preamble(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_serialization")

    check_serialization(model, x)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_double_fit(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test Double fit."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_double_fit")

    check_double_fit(model_class, n_bits, x, y)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_offset(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test with offset."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_offset")

    check_offset(model_class, n_bits, x, y)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
@pytest.mark.parametrize("input_type", ["numpy", "torch", "pandas", "list"])
# pylint: disable=too-many-arguments
def test_input_support(
    model_class,
    parameters,
    n_bits,
    load_data,
    input_type,
    default_configuration,
    is_weekly_option,
    verbose=True,
):
    """Test all models with Pandas, List or Torch inputs."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run input_support")

    check_input_support(model_class, n_bits, default_configuration, x, y, input_type)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_subfunctions(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test subfunctions."""
    model, x = preamble(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_subfunctions")

    check_subfunctions(model, model_class, x)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "n_bits",
    N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS,
)
# pylint: disable=too-many-arguments
def test_pipeline(
    model_class,
    parameters,
    n_bits,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test with pipelines."""
    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_pipeline")

    check_pipeline(model_class, x, y)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "simulate",
    [
        pytest.param(False, id="fhe"),
        pytest.param(True, id="simulate"),
    ],
)
@pytest.mark.parametrize(
    "n_bits",
    [
        n
        for n in N_BITS_WEEKLY_ONLY_BUILDS + N_BITS_REGULAR_BUILDS
        if n >= N_BITS_THRESHOLD_FOR_PREDICT_CORRECTNESS_TESTS
    ],
)
# pylint: disable=too-many-arguments, too-many-branches
def test_predict_correctness(
    model_class,
    parameters,
    simulate,
    n_bits,
    load_data,
    default_configuration,
    check_is_good_execution_for_cml_vs_circuit,
    check_circuit_has_no_tlu,
    is_weekly_option,
    test_subfunctions_in_fhe=True,
    verbose=True,
):
    """Test correct execution, if there is sufficiently n_bits."""

    # Will be reverted when it works
    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/3118
    # FIXME: https://github.com/zama-ai/concrete-numpy-internal/issues/1859
    if (
        (n_bits >= N_BITS_THRESHOLD_FOR_CRT_FHE_CIRCUITS)
        and (model_class in get_sklearn_tree_models())
        and not simulate
    ):
        pytest.skip("Skipping while bug concrete-numpy-internal/issues/1859 is being investigated")

    model, x = preamble(model_class, parameters, n_bits, load_data, is_weekly_option)

    # How many samples for tests in FHE (ie, predict with fhe = "execute" or "simulate")
    if is_weekly_option or simulate:
        number_of_tests_in_fhe = 5
    else:
        number_of_tests_in_fhe = 1

    # How many samples for tests in quantized module (ie, predict with fhe = "disable")
    if is_weekly_option:
        number_of_tests_in_non_fhe = 50
    else:
        number_of_tests_in_non_fhe = 10

    # Do some inferences in clear
    if verbose:
        print(
            "Inference in the clear (with "
            f"number_of_tests_in_non_fhe = {number_of_tests_in_non_fhe})"
        )

    y_pred = model.predict(x[:number_of_tests_in_non_fhe])

    list_of_possibilities = [False, True]

    # Prevent computations in FHE if too many bits
    if n_bits >= N_BITS_THRESHOLD_TO_FORCE_EXECUTION_NOT_IN_FHE:
        list_of_possibilities = [False]

    for test_with_execute_in_fhe in list_of_possibilities:

        # N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS bits is currently the
        # limit to find crypto parameters for linear models
        # make sure we only compile below that bit-width.
        if test_with_execute_in_fhe and not n_bits >= N_BITS_LINEAR_MODEL_CRYPTO_PARAMETERS:

            if verbose:
                print("Compile the model")

            with warnings.catch_warnings():
                fhe_circuit = model.compile(
                    x,
                    default_configuration,
                    show_mlir=verbose and (n_bits <= 8),
                )

                check_properties_of_circuit(model_class, fhe_circuit, check_circuit_has_no_tlu)

            if verbose:
                print("Compilation done")

            if verbose:
                print(
                    "Run check_is_good_execution_for_cml_vs_circuit "
                    + f"(with number_of_tests_in_fhe = {number_of_tests_in_fhe})"
                )

            # Check the `predict` method
            check_is_good_execution_for_cml_vs_circuit(
                x[:number_of_tests_in_fhe], model=model, simulate=simulate
            )

            if test_subfunctions_in_fhe and (not simulate):
                if verbose:
                    print("Testing subfunctions in FHE")

                check_subfunctions_in_fhe(model, fhe_circuit, x[:number_of_tests_in_fhe])

        else:
            if verbose:
                print(
                    "Run predict in fhe='disable' "
                    f"(with number_of_tests_in_non_fhe = {number_of_tests_in_non_fhe})"
                )

            # At least, check in clear mode
            y_pred_fhe = model.predict(x[:number_of_tests_in_non_fhe], fhe="disable")

            # Check that the output shape is correct
            assert y_pred_fhe.shape == y_pred.shape
            assert numpy.array_equal(y_pred_fhe, y_pred)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
def test_fitted_compiled_error_raises(
    model_class,
    parameters,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test Fit and Compile error raises."""
    n_bits = min(N_BITS_REGULAR_BUILDS)

    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    if verbose:
        print("Run check_fitted_compiled_error_raises")

    check_fitted_compiled_error_raises(model_class, n_bits, x, y)


@pytest.mark.parametrize("model_class, parameters", sklearn_models_and_datasets)
@pytest.mark.parametrize(
    "error_param",
    [{"p_error": 0.9999999999990905}],  # 1 - 2**-40
    ids=["p_error"],
)
def test_p_error_global_p_error_simulation(
    model_class,
    parameters,
    error_param,
    load_data,
    is_weekly_option,
):
    """Test p_error and global_p_error simulation.

    Description:
        A model is compiled with a large p_error. The test then checks the predictions for
        simulated and fully homomorphic encryption (FHE) inference, and asserts
        that the predictions for both are different from the exepceted predictions.
    """
    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/3297
    if "global_p_error" in error_param:
        pytest.skip("global_p_error behave very differently depending on the type of model.")

    # Get dataset
    n_bits = min(N_BITS_REGULAR_BUILDS)

    # Initialize and fit the model
    model, x = preamble(model_class, parameters, n_bits, load_data, is_weekly_option)

    # Check if model is linear
    is_linear_model = is_model_class_in_a_list(model_class, get_sklearn_linear_models())

    # Compile with a large p_error to be sure the result is random.
    model.compile(x, **error_param)

    def check_for_divergent_predictions(x, model, fhe, max_iterations=N_ALLOWED_FHE_RUN):
        """Detect divergence between simulated/FHE execution and clear run."""
        predict_function = (
            model.predict_proba if is_classifier_or_partial_classifier(model) else model.predict
        )
        y_expected = predict_function(x, fhe="disable")
        for i in range(max_iterations):
            y_pred = predict_function(x[i : i + 1], fhe=fhe).ravel()
            if not numpy.array_equal(y_pred, y_expected[i : i + 1].ravel()):
                return True
        return False

    simulation_diff_found = check_for_divergent_predictions(x, model, fhe="simulate")
    fhe_diff_found = check_for_divergent_predictions(x, model, fhe="execute")

    # Check for differences in predictions
    if is_linear_model:

        # In FHE, high p_error affect the crypto parameters which
        # makes the predictions slighlty different
        assert fhe_diff_found, "FHE predictions should be different for linear models"

        # linear models p_error is not simulated
        assert not simulation_diff_found, "SIMULATE predictions not the same for linear models"
    else:
        assert fhe_diff_found and simulation_diff_found, (
            f"Predictions not different in at least one run.\n"
            f"FHE predictions differ: {fhe_diff_found}\n"
            f"SIMULATE predictions differ: {simulation_diff_found}"
        )


@pytest.mark.parametrize("model_class, parameters", _classifiers_and_datasets)
def test_class_mapping(
    model_class,
    parameters,
    load_data,
    is_weekly_option,
    verbose=True,
):
    """Test class mapping for classifiers."""
    n_bits = min(N_BITS_REGULAR_BUILDS)

    x, y = get_dataset(model_class, parameters, n_bits, load_data, is_weekly_option)

    model = instantiate_model_generic(model_class, n_bits=n_bits)

    if verbose:
        print("Run check_class_mapping")

    check_class_mapping(model, x, y)
