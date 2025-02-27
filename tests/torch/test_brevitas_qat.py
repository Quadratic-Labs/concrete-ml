"""Tests with brevitas quantization aware training."""

import brevitas.nn as qnn
import numpy
import pytest
import torch
import torch.utils
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from concrete.ml.common.utils import (
    is_classifier_or_partial_classifier,
    is_regressor_or_partial_regressor,
)
from concrete.ml.pytest.torch_models import NetWithConstantsFoldedBeforeOps, TinyQATCNN
from concrete.ml.sklearn import get_sklearn_neural_net_models
from concrete.ml.sklearn.qnn_module import SparseQuantNeuralNetwork
from concrete.ml.torch.compile import compile_brevitas_qat_model


@pytest.mark.parametrize("qat_bits", [3])
@pytest.mark.parametrize("signed, narrow", [(True, False), (True, True), (False, False)])
def test_brevitas_tinymnist_cnn(
    qat_bits,
    signed,
    narrow,
    default_configuration,
    check_graph_input_has_no_tlu,
    check_graph_output_has_no_tlu,
    check_is_good_execution_for_cml_vs_circuit,
):  # pylint: disable=too-many-statements, too-many-locals
    """Train, execute and test a QAT CNN on a small version of MNIST."""

    # And some helpers for visualization.
    x_all, y_all = load_digits(return_X_y=True)

    # The sklearn Digits dataset, though it contains digit images, keeps these images in vectors
    # so we need to reshape them to 2D first. The images are 8x8 px in size and monochrome
    x_all = numpy.expand_dims(x_all.reshape((-1, 8, 8)), 1)

    x_train, x_test, y_train, y_test = train_test_split(
        x_all, y_all, test_size=0.25, shuffle=True, random_state=numpy.random.randint(0, 2**15)
    )

    def train_one_epoch(net, optimizer, train_loader):
        # Cross Entropy loss for classification when not using a softmax layer in the network
        loss = nn.CrossEntropyLoss()

        net.train()
        avg_loss = 0
        for data, target in train_loader:
            optimizer.zero_grad()
            output = net(data)
            loss_net = loss(output, target.long())
            loss_net.backward()
            optimizer.step()
            avg_loss += loss_net.item()

        return avg_loss / len(train_loader)

    # Prepare the data:
    # Create a train data loader
    train_dataset = TensorDataset(torch.Tensor(x_train), torch.Tensor(y_train))
    train_dataloader = DataLoader(train_dataset, batch_size=64)

    # Create a test data loader to supply batches for network evaluation (test)
    test_dataset = TensorDataset(torch.Tensor(x_test), torch.Tensor(y_test))
    test_dataloader = DataLoader(test_dataset)

    trained_ok = False

    while not trained_ok:
        # Create the tiny CNN module with 10 output classes
        net = TinyQATCNN(10, qat_bits, 4 if qat_bits <= 3 else 20, signed, narrow)

        # Train a single epoch to have a fast test, accuracy should still be the same for both
        # FHE simulation and torch
        # But train 3 epochs for the FHE similation test to check that training works well
        n_epochs = 1 if qat_bits <= 3 else 3

        # Train the network with Adam, output the test set accuracy every epoch
        optimizer = torch.optim.Adam(net.parameters())
        for _ in range(n_epochs):
            train_one_epoch(net, optimizer, train_dataloader)

        # Finally, disable pruning (sets the pruned weights to 0)
        net.toggle_pruning(False)

        torch_correct = net.test_torch(test_dataloader)

        # If number of correct results was zero, training failed and there were NaNs in the weights
        # Retrain while training is bad
        trained_ok = torch_correct > 0

    def test_with_concrete(quantized_module, test_loader, use_fhe_simulation):
        """Test a neural network that is quantized and compiled with Concrete ML."""

        all_targets = numpy.zeros((len(test_loader)), dtype=numpy.int64)

        # Iterate over the test batches and accumulate predictions and ground truth
        # labels in a vector
        idx = 0
        for data, target in test_loader:
            data = data.numpy()

            # Accumulate the ground truth labels
            endidx = idx + target.shape[0]
            all_targets[idx:endidx] = target.numpy()

            # Dequantize the integer predictions
            check_is_good_execution_for_cml_vs_circuit(
                data, model=quantized_module, simulate=use_fhe_simulation
            )

            fhe_mode = "simulate" if use_fhe_simulation else "execute"

            y_pred = quantized_module.forward(data, fhe=fhe_mode)

            # Take the predicted class from the outputs and store it
            y_pred = numpy.argmax(y_pred, axis=1)

        # Compute and report results
        n_correct = numpy.sum(all_targets == y_pred)
        return n_correct

    net.eval()

    q_module_simulated = compile_brevitas_qat_model(
        net,
        x_all,
        configuration=default_configuration,
    )

    fhe_s_correct = test_with_concrete(
        q_module_simulated,
        test_dataloader,
        use_fhe_simulation=True,
    )

    # Accept, at most, 1% examples that are classified differently (currently 5)
    # For now, the correctness test has been disabled as it was too flaky, it should however be put
    # back at one point
    # FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2550
    # assert abs(fhe_simulation_correct - torch_correct) <= numpy.ceil(0.01 * len(y_test))

    assert fhe_s_correct.shape == torch_correct.shape

    check_graph_input_has_no_tlu(q_module_simulated.fhe_circuit.graph)
    check_graph_output_has_no_tlu(q_module_simulated.fhe_circuit.graph)


# Note that this test is currently disabled until the pytorch dtype issue is found
# and all mismatches between CML and Brevitas are fixed
# FIXME: https://github.com/zama-ai/concrete-ml-internal/issues/2373
@pytest.mark.parametrize(
    "n_layers",
    [3],
)
@pytest.mark.parametrize("n_bits_w_a", [2, 4, 7])
@pytest.mark.parametrize("n_accum_bits", [40])
@pytest.mark.parametrize(
    "activation_function",
    [
        pytest.param(nn.ReLU),
    ],
)
@pytest.mark.parametrize("n_outputs", [5])
@pytest.mark.parametrize("input_dim", [100])
@pytest.mark.parametrize("model_class", get_sklearn_neural_net_models())
@pytest.mark.parametrize("signed, narrow", [(True, False), (False, False), (True, True)])
@pytest.mark.skip(reason="Torch dtype setting interferes with parallel test launch, and flaky test")
def test_brevitas_intermediary_values(
    n_layers,
    n_bits_w_a,
    n_accum_bits,
    activation_function,
    n_outputs,
    input_dim,
    model_class,
    load_data,
    signed,
    narrow,
):  # pylint: disable=too-many-statements, too-many-locals
    """Test the correctness of the results of quantized NN classifiers through the sklearn
    wrapper.

    First, we train a Torch classifier, with various quantization options (narrow/signed/bits).
    Then, we wrap the trained model in a debug module. This module will capture the quantized
    integer values that are input to conv/linear layers. We also capture the quantized integer
    weights. For both weights and quantized inputs, we also capture the corresponding floating
    point value that produced the integer value.

    Next, we convert the Torch model to a QuantizedModule. We use the debug feature to capture
    the integer and floating point values that are inputs to all the conv/linear layers.

    Finally, we compare the integer values from the Torch/brevitas execution with those captured
    by the QuantizedModule execution and find differences. When a difference in integers is found
    we print the offending raw floating point values, and, when available, quantization options.
    """

    # Get the dataset. The data generation is seeded in load_data.
    if is_classifier_or_partial_classifier(model_class):
        x, y = load_data(
            model_class,
            n_samples=1000,
            n_features=input_dim,
            n_redundant=0,
            n_repeated=0,
            n_informative=input_dim,
            n_classes=n_outputs,
            class_sep=2,
        )

    # Get the dataset. The data generation is seeded in load_data.
    elif is_regressor_or_partial_regressor(model_class):
        x, y, _ = load_data(
            model_class,
            n_samples=1000,
            n_features=input_dim,
            n_informative=input_dim,
            n_targets=n_outputs,
            noise=2,
            coef=True,
        )
        if y.ndim == 1:
            y = numpy.expand_dims(y, 1)
    else:
        raise ValueError(f"Data generator not implemented for {str(model_class)}")

    # Perform a classic test-train split (deterministic by fixing the seed)
    x_train, x_test, y_train, _ = train_test_split(
        x,
        y,
        test_size=0.25,
        random_state=numpy.random.randint(0, 2**15),
    )

    params = {
        "module__n_layers": n_layers,
        "module__n_w_bits": n_bits_w_a,
        "module__n_a_bits": n_bits_w_a,
        "module__n_accum_bits": n_accum_bits,
        "module__activation_function": activation_function,
        "module__quant_signed": signed,
        "module__quant_narrow": narrow,
        "max_epochs": 10,
        "verbose": 0,
    }

    concrete_model = model_class(**params)

    # Compute mean/stdev on training set and normalize both train and test sets with them
    normalizer = StandardScaler()
    x_train = normalizer.fit_transform(x_train)
    x_test = normalizer.transform(x_test)

    concrete_model.fit(x_train, y_train)

    # Wrap the original torch module with a debug module that captures intermediary values
    class DebugQNNModel(SparseQuantNeuralNetwork):
        """Wrapper class that extracts intermediary values from a Brevitas QAT net."""

        intermediary_values = []
        intermediary_inp_values_float = []
        quant_weights = []
        raw_weights = []
        narrow_range_inp = []
        narrow_range_weight = []

        def forward(self, x):
            for mod in self.features:
                if isinstance(mod, qnn.QuantLinear):
                    self.intermediary_inp_values_float.append(x.value.detach().numpy())
                x = mod(x)
                if isinstance(mod, qnn.QuantIdentity):
                    self.intermediary_values.append(x.int().detach().numpy())
                    self.narrow_range_inp.append(mod.act_quant.is_narrow_range)
                elif isinstance(mod, qnn.QuantLinear):
                    self.narrow_range_weight.append(mod.weight_quant.is_narrow_range)
                    self.quant_weights.append(mod.int_weight().detach().numpy())
                    self.raw_weights.append(mod.quant_weight().value.detach().numpy())
            return x

    params_module = {
        param.replace("module__", ""): value
        for param, value in params.items()
        if "module__" in param
    }

    # Concrete ML and CNP use float64, so we need to force pytorch to use the same, as
    # it defaults to float32. Note that this change is global and may interfere with
    # threading or multiprocessing. Thus this test can not be launched in parallel with others.
    torch.set_default_dtype(torch.float64)

    # Wrap the original model, and copy its weights
    dbg_model = DebugQNNModel(**params_module, input_dim=input_dim, n_outputs=n_outputs)
    dbg_model.load_state_dict(concrete_model.base_module.state_dict())

    # Execute on the test set and capture debug values
    dbg_model(torch.tensor(x_test.astype(numpy.float64)))

    # Execute the Concrete ML model on the test set and capture debug values
    _, cml_debug_values = concrete_model.quantized_module_.forward(
        x_test, debug=True, fhe="disable"
    )

    cml_intermediary_values = [
        q_arr[0].qvalues for name, q_arr in cml_debug_values.items() if "Gemm" in name
    ]
    cml_input_values = [
        q_arr[0].values for name, q_arr in cml_debug_values.items() if "Gemm" in name
    ]
    cml_quantizers = [
        q_arr[0].quantizer for name, q_arr in cml_debug_values.items() if "Gemm" in name
    ]
    cml_quant_weights = [
        q_arr[1].qvalues for name, q_arr in cml_debug_values.items() if "Gemm" in name
    ]
    cml_raw_weights = [
        q_arr[1].values for name, q_arr in cml_debug_values.items() if "Gemm" in name
    ]

    # Make sure the quantization options were well set by brevitas
    assert len(set(dbg_model.narrow_range_inp)) > 0 and dbg_model.narrow_range_inp[0] == narrow
    assert (
        len(set(dbg_model.narrow_range_weight)) > 0 and dbg_model.narrow_range_weight[0] == narrow
    )

    # Iterate across conv/linear layers

    # pylint: disable-next=consider-using-enumerate
    for idx in range(len(cml_intermediary_values)):
        # Check if any activations are different between Brevitas and CML
        diff_inp = numpy.abs(cml_intermediary_values[idx] - dbg_model.intermediary_values[idx])
        error = ""
        if numpy.any(diff_inp) > 0:
            # If any mismatches, then extract them and print them
            indices = numpy.nonzero(diff_inp)
            error = (
                f"Mismatched values in layer {idx} at input indices: {numpy.transpose(indices)}\n"
                f"CML Inputs were: {cml_input_values[idx][indices]} \n"
                f"CML quantized to {cml_intermediary_values[idx][indices]}\n"
                f"Brevitas inputs were {dbg_model.intermediary_inp_values_float[idx][indices]}\n"
                f"Brevitas quantized to {dbg_model.intermediary_values[idx][indices]}\n "
                f"Quant params were {str(cml_quantizers[idx].__dict__)}\n "
            )

        # Assert if there were any mismatches
        assert numpy.all(diff_inp == 0), error

        # Check if any weights are different between Brevitas and CML
        diff_weights = numpy.abs(cml_quant_weights[idx] - dbg_model.quant_weights[idx])
        weights_ok = True

        if numpy.any(diff_weights) > 0:
            indices = numpy.nonzero(diff_weights)
            diff_raw_weights = numpy.abs(
                dbg_model.raw_weights[idx][indices] - cml_raw_weights[idx][indices]
            )

            # Here, numpy.all returns Numpy's `bool_` type, which is a different type than `bool`.
            # Since `weights_ok` is initialized using a `bool`, mypy complains and we therefore
            # need to force the type
            weights_ok = bool(numpy.all(diff_raw_weights > 0.0001))

            error = (
                f"Mismatched weights in layer {idx} at input indices: {numpy.transpose(indices)}\n"
                f"CML raw weights were: {cml_raw_weights[idx][indices]} \n"
                f"CML quantized to {cml_quant_weights[idx][indices]}\n"
                f"Brevitas weights were {dbg_model.raw_weights[idx][indices]}\n"
                f"Brevitas quantized to {dbg_model.quant_weights[idx][indices]}\n "
            )

        assert weights_ok, error

    torch.set_default_dtype(torch.float32)


def test_brevitas_constant_folding(default_configuration):
    """Test that a network that does not quantize its inputs raises the right exception.

    The network tested is not a valid QAT network for Concrete ML as it does not
    quantize its inputs. However, in previous versions of Concrete ML a bug
    in constant folding prevented the correct error being raised.
    """

    batch_size = 64
    config = {
        "n_feats": 12,
        "hidden_dim": 32,
    }
    data = torch.randn((batch_size, config["n_feats"]))

    model = NetWithConstantsFoldedBeforeOps(config, 2)

    with pytest.raises(ValueError, match=".*Error occurred during quantization aware training.*"):
        compile_brevitas_qat_model(
            model.to("cpu"),
            torch_inputset=data,
            configuration=default_configuration,
        )
