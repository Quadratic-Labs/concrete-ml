<!-- markdownlint-disable -->

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `concrete.ml.common.utils`

Utils that can be re-used by other pieces of code in the module.

## **Global Variables**

- **SUPPORTED_FLOAT_TYPES**
- **SUPPORTED_INT_TYPES**
- **MAX_BITWIDTH_BACKWARD_COMPATIBLE**

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L79"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `replace_invalid_arg_name_chars`

```python
replace_invalid_arg_name_chars(arg_name: str) → str
```

Sanitize arg_name, replacing invalid chars by \_.

This does not check that the starting character of arg_name is valid.

**Args:**

- <b>`arg_name`</b> (str):  the arg name to sanitize.

**Returns:**

- <b>`str`</b>:  the sanitized arg name, with only chars in \_VALID_ARG_CHARS.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L98"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `generate_proxy_function`

```python
generate_proxy_function(
    function_to_proxy: Callable,
    desired_functions_arg_names: Iterable[str]
) → Tuple[Callable, Dict[str, str]]
```

Generate a proxy function for a function accepting only \*args type arguments.

This returns a runtime compiled function with the sanitized argument names passed in desired_functions_arg_names as the arguments to the function.

**Args:**

- <b>`function_to_proxy`</b> (Callable):  the function defined like def f(\*args) for which to return a  function like f_proxy(arg_1, arg_2) for any number of arguments.
- <b>`desired_functions_arg_names`</b> (Iterable\[str\]):  the argument names to use, these names are  sanitized and the mapping between the original argument name to the sanitized one is  returned in a dictionary. Only the sanitized names will work for a call to the proxy  function.

**Returns:**

- <b>`Tuple[Callable, Dict[str, str]]`</b>:  the proxy function and the mapping of the original arg name  to the new and sanitized arg names.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L139"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_onnx_opset_version`

```python
get_onnx_opset_version(onnx_model: ModelProto) → int
```

Return the ONNX opset_version.

**Args:**

- <b>`onnx_model`</b> (onnx.ModelProto):  the model.

**Returns:**

- <b>`int`</b>:  the version of the model

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L154"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `manage_parameters_for_pbs_errors`

```python
manage_parameters_for_pbs_errors(
    p_error: Optional[float] = None,
    global_p_error: Optional[float] = None
)
```

Return (p_error, global_p_error) that we want to give to Concrete.

The returned (p_error, global_p_error) depends on user's parameters and the way we want to manage defaults in Concrete ML, which may be different from the way defaults are managed in Concrete.

Principle:
\- if none are set, we set global_p_error to a default value of our choice
\- if both are set, we raise an error
\- if one is set, we use it and forward it to Concrete

Note that global_p_error is currently set to 0 in the FHE simulation mode.

**Args:**

- <b>`p_error`</b> (Optional\[float\]):  probability of error of a single PBS.
- <b>`global_p_error`</b> (Optional\[float\]):  probability of error of the full circuit.

**Returns:**

- <b>`(p_error, global_p_error)`</b>:  parameters to give to the compiler

**Raises:**

- <b>`ValueError`</b>:  if the two parameters are set (this is _not_ as in Concrete-Python)

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L199"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `check_there_is_no_p_error_options_in_configuration`

```python
check_there_is_no_p_error_options_in_configuration(configuration)
```

Check the user did not set p_error or global_p_error in configuration.

It would be dangerous, since we set them in direct arguments in our calls to Concrete-Python.

**Args:**

- <b>`configuration`</b>:  Configuration object to use  during compilation

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L220"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_model_class`

```python
get_model_class(model_class)
```

Return the class of the model (instantiated or not), which can be a partial() instance.

**Args:**

- <b>`model_class`</b>:  The model, which can be a partial() instance.

**Returns:**
The model's class.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L242"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_model_class_in_a_list`

```python
is_model_class_in_a_list(model_class, a_list)
```

Indicate if a model class, which can be a partial() instance, is an element of a_list.

**Args:**

- <b>`model_class`</b>:  The model, which can be a partial() instance.
- <b>`a_list`</b>:  The list in which to look into.

**Returns:**
If the model's class is in the list or not.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L256"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_model_name`

```python
get_model_name(model_class)
```

Return the name of the model, which can be a partial() instance.

**Args:**

- <b>`model_class`</b>:  The model, which can be a partial() instance.

**Returns:**
the model's name.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L269"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_classifier_or_partial_classifier`

```python
is_classifier_or_partial_classifier(model_class)
```

Indicate if the model class represents a classifier.

**Args:**

- <b>`model_class`</b>:  The model class, which can be a functool's `partial` class.

**Returns:**

- <b>`bool`</b>:  If the model class represents a classifier.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L281"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_regressor_or_partial_regressor`

```python
is_regressor_or_partial_regressor(model_class)
```

Indicate if the model class represents a regressor.

**Args:**

- <b>`model_class`</b>:  The model class, which can be a functool's `partial` class.

**Returns:**

- <b>`bool`</b>:  If the model class represents a regressor.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L293"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_pandas_dataframe`

```python
is_pandas_dataframe(input_container: Any) → bool
```

Indicate if the input container is a Pandas DataFrame.

This function is inspired from Scikit-Learn's test validation tools and avoids the need to add and import Pandas as an additional dependency to the project. See https://github.com/scikit-learn/scikit-learn/blob/98cf537f5/sklearn/utils/validation.py#L629

**Args:**

- <b>`input_container`</b> (Any):  The input container to consider

**Returns:**

- <b>`bool`</b>:  If the input container is a DataFrame

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L309"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_pandas_series`

```python
is_pandas_series(input_container: Any) → bool
```

Indicate if the input container is a Pandas Series.

This function is inspired from Scikit-Learn's test validation tools and avoids the need to add and import Pandas as an additional dependency to the project. See https://github.com/scikit-learn/scikit-learn/blob/98cf537f5/sklearn/utils/validation.py#L629

**Args:**

- <b>`input_container`</b> (Any):  The input container to consider

**Returns:**

- <b>`bool`</b>:  If the input container is a Series

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L325"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_pandas_type`

```python
is_pandas_type(input_container: Any) → bool
```

Indicate if the input container is a Pandas DataFrame or Series.

**Args:**

- <b>`input_container`</b> (Any):  The input container to consider

**Returns:**

- <b>`bool`</b>:  If the input container is a DataFrame orSeries

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L420"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `check_dtype_and_cast`

```python
check_dtype_and_cast(
    values: Any,
    expected_dtype: str,
    error_information: Optional[str] = ''
)
```

Convert any allowed type into an array and cast it if required.

If values types don't match with any supported type or the expected dtype, raise a ValueError.

**Args:**

- <b>`values`</b> (Any):  The values to consider
- <b>`expected_dtype`</b> (str):  The expected dtype, either "float32" or "int64"
- <b>`error_information`</b> (str):  Additional information to put in front of the error message when  raising a ValueError. Default to None.

**Returns:**

- <b>`(Union[numpy.ndarray, torch.utils.data.dataset.Subset])`</b>:  The values with proper dtype.

**Raises:**

- <b>`ValueError`</b>:  If the values' dtype don't match the expected one or casting is not possible.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L472"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `compute_bits_precision`

```python
compute_bits_precision(x: ndarray) → int
```

Compute the number of bits required to represent x.

**Args:**

- <b>`x`</b> (numpy.ndarray):  Integer data

**Returns:**

- <b>`int`</b>:  the number of bits required to represent x

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L484"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_brevitas_model`

```python
is_brevitas_model(model: Module) → bool
```

Check if a model is a Brevitas type.

**Args:**

- <b>`model`</b>:  PyTorch model.

**Returns:**

- <b>`bool`</b>:  True if `model` is a Brevitas network.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L502"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `to_tuple`

```python
to_tuple(x: Any) → tuple
```

Make the input a tuple if it is not already the case.

**Args:**

- <b>`x`</b> (Any):  The input to consider. It can already be an input.

**Returns:**

- <b>`tuple`</b>:  The input as a tuple.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L518"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `all_values_are_integers`

```python
all_values_are_integers(*values: Any) → bool
```

Indicate that all unpacked values are of a supported integer dtype.

**Args:**

- <b>`*values (Any)`</b>:  The values to consider.

**Returns:**

- <b>`bool`</b>:  Wether all values are supported integers or not.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L531"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `all_values_are_floats`

```python
all_values_are_floats(*values: Any) → bool
```

Indicate that all unpacked values are of a supported float dtype.

**Args:**

- <b>`*values (Any)`</b>:  The values to consider.

**Returns:**

- <b>`bool`</b>:  Wether all values are supported floating points or not.

______________________________________________________________________

<a href="https://github.com/zama-ai/concrete-ml-internal/tree/main/src/concrete/ml/common/utils.py#L36"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `FheMode`

Enum representing the execution mode.

This enum inherits from str in order to be able to easily compare a string parameter to its equivalent Enum attribute.

**Examples:**
fhe_disable = FheMode.DISABLE

` fhe_disable == "disable"`
True

```
 >>> fhe_disable == "execute"
 False

 >>> FheMode.is_valid("simulate")
 True

 >>> FheMode.is_valid(FheMode.EXECUTE)
 True

 >>> FheMode.is_valid("predict_in_fhe")
 False
```
