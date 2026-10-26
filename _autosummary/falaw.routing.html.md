# falaw.routing

Which model a router call really goes to (falaw#115).

`fal-ai/any-llm` is one catalogue record that routes many upstream models.
The routed model is who serves, prices and licenses the call, so both the rate
table ([`falaw.llm_rates`](falaw.llm_rates.html.md#module-falaw.llm_rates)) and the terms ledger ([`falaw.terms`](falaw.terms.html.md#module-falaw.terms)) judge
it, not the router. This module is the one place that knows which applications
route and by which argument.

```pycon
>>> routed_model("fal-ai/any-llm", {"model": "anthropic/claude-sonnet-4.5"})
'anthropic/claude-sonnet-4.5'
>>> routed_model("fal-ai/flux/dev", {"model": "ignored"})
'fal-ai/flux/dev'
```

### Module Attributes

| [`ANY_LLM`](#falaw.routing.ANY_LLM)   | The application that routes an LLM call to one of many upstream models.     |
|------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`ROUTERS`](#falaw.routing.ROUTERS)   | Applications that route to another model, mapped to the argument naming it. |

### Functions

| [`routed_model`](#falaw.routing.routed_model)(application[, arguments])   | The model that serves the call: the one a router's argument names, else *application* itself.   |
|-------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|

### falaw.routing.ANY_LLM *= 'fal-ai/any-llm'*

The application that routes an LLM call to one of many upstream models.

### falaw.routing.ROUTERS *= mappingproxy({'fal-ai/any-llm': 'model', 'fal-ai/any-llm/vision': 'model'})*

Applications that route to another model, mapped to the argument naming it.

### falaw.routing.routed_model(application, arguments=None)

The model that serves the call: the one a router’s argument names, else
*application* itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
