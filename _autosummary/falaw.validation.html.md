# falaw.validation

Check a call’s arguments against the limits its catalogue record states.

The data-driven seam for request-shape limits that fal would otherwise reject
with an HTTP 422 after queueing: `param_specs[name]` may carry `max_items`
(a list argument such as reference images) and `min_pixels` / `max_pixels`
(an explicit `{"width", "height"}` size). One function, called from the two
places every call passes through — [`falaw.make_call_plan()`](falaw.html.md#falaw.make_call_plan) and
[`falaw.call_fal()`](falaw.html.md#falaw.call_fal) — so no planner or eager verb can forget it.

### Functions

| [`check_call_arguments`](#falaw.validation.check_call_arguments)(record, arguments)   | Raise `ValueError` if `arguments` break a limit `record` states: list sizes, pixel counts, and the prompt's `max_prompt_chars` for every operation (not only text-to-image, falaw#170).   |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_prompt_length`](#falaw.validation.check_prompt_length)(prompt, record)       | Raise `FalPromptTooLong` when `prompt` exceeds the model's cap.                                                                                                                           |

### falaw.validation.check_call_arguments(record, arguments)

Raise `ValueError` if `arguments` break a limit `record` states: list
sizes, pixel counts, and the prompt’s `max_prompt_chars` for every operation
(not only text-to-image, falaw#170).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.validation.check_prompt_length(prompt, record)

Raise `FalPromptTooLong` when `prompt` exceeds the model’s cap.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
