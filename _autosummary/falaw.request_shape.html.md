# falaw.request_shape

What a model’s request accepts, read from fal’s published OpenAPI schema (falaw#159).

A [`ModelRecord`](falaw.base.html.md#falaw.base.ModelRecord) carries request-shape facts a planner acts
on: `accepts_negative_prompt` (send a negative prompt, or drop it),
`max_prompt_chars` (refuse a prompt fal would 422 after queueing) and
`size_param` (`image_size` presets, or `aspect_ratio`). Set by hand they
rot, and a `False` read both “checked: no such input” and “never checked”.
Here they are derived from one fetched fact, the model’s input property names
(`accepted_inputs`; `None` on a record means never fetched):

- [`input_properties()`](#falaw.request_shape.input_properties): the `POST` request body’s properties, from the
  OpenAPI document fal serves per endpoint (the one [`falaw.liveness`](falaw.liveness.html.md#module-falaw.liveness)
  probes: free, no key);
- [`request_shape()`](#falaw.request_shape.request_shape): those properties as the record’s fields;
- [`refresh_request_shapes()`](#falaw.request_shape.refresh_request_shapes): fetch every catalogued model (or `ids`),
  and with `write=True` put the fields into `falaw/data/models.json`. Then
  run `python -m falaw export-schema` and the TS codegen, as for any
  catalogue change.

```pycon
>>> doc = {"paths": {"/fal-ai/x": {"post": {"requestBody": {"content": {"application/json":
...     {"schema": {"$ref": "#/components/schemas/XInput"}}}}}}},
...     "components": {"schemas": {"XInput": {"properties": {
...         "prompt": {"type": "string", "maxLength": 1000}, "negative_prompt": {"type": "string"},
...         "image_size": {"$ref": "#/components/schemas/ImageSize"}}}}}}
>>> shape = request_shape(input_properties(doc))
>>> shape["accepted_inputs"], shape["accepts_negative_prompt"], shape["max_prompt_chars"]
(['image_size', 'negative_prompt', 'prompt'], True, 1000)
```

### Module Attributes

| [`JsonGetter`](#falaw.request_shape.JsonGetter)       | `url -> parsed JSON`; injectable so tests never touch the network.                                           |
|-------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`IMAGE_SIZE_PARAM`](#falaw.request_shape.IMAGE_SIZE_PARAM) | The input that sizes an image by fal's named presets; the alternative is `aspect_ratio` (with `resolution`). |
| [`SHAPE_FIELDS`](#falaw.request_shape.SHAPE_FIELDS)     | The record fields a refresh writes.                                                                          |

### Functions

| [`fetch_request_shape`](#falaw.request_shape.fetch_request_shape)(endpoint_id, \*[, get_json])   | [`request_shape()`](#falaw.request_shape.request_shape) of one endpoint, from fal's OpenAPI document; `None` for an endpoint fal no longer serves (a 404, [`falaw.liveness`](falaw.liveness.html.md#module-falaw.liveness)).                                                                     |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`input_properties`](#falaw.request_shape.input_properties)(doc)                              | The input properties (`{name: schema}`) of the `POST` request body in an endpoint's OpenAPI document, `$ref``s resolved and ``allOf` merged, each with its `maxLength` lifted out of an `anyOf`.                                                                                                                               |
| [`refresh_request_shapes`](#falaw.request_shape.refresh_request_shapes)([ids, get_json, ...])       | `{endpoint_id: shape}` for `ids` (default: every catalogued model), each fetched from fal.                                                                                                                                                                                                                                     |
| [`request_shape`](#falaw.request_shape.request_shape)(properties)                          | The record fields ([`SHAPE_FIELDS`](#falaw.request_shape.SHAPE_FIELDS)) an endpoint's input properties imply: their names (sorted), whether `negative_prompt` is one, the `prompt`'s `maxLength` (`None` when it states none), and the size input (`aspect_ratio` only when the model takes it and no `image_size`). |

### falaw.request_shape.IMAGE_SIZE_PARAM *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'image_size'*

The input that sizes an image by fal’s named presets; the alternative is
`aspect_ratio` (with `resolution`).

### falaw.request_shape.JsonGetter

`url -> parsed JSON`; injectable so tests never touch the network.

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### falaw.request_shape.SHAPE_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('accepted_inputs', 'accepts_negative_prompt', 'max_prompt_chars', 'size_param')*

The record fields a refresh writes.

### falaw.request_shape.fetch_request_shape(endpoint_id, , get_json=None)

[`request_shape()`](#falaw.request_shape.request_shape) of one endpoint, from fal’s OpenAPI document;
`None` for an endpoint fal no longer serves (a 404, [`falaw.liveness`](falaw.liveness.html.md#module-falaw.liveness)).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.request_shape.input_properties(doc)

The input properties (`{name: schema}`) of the `POST` request body in
an endpoint’s OpenAPI document, `$ref``s resolved and ``allOf` merged, each
with its `maxLength` lifted out of an `anyOf`. `ValueError` when the
document has no such body or it has no properties: an empty answer would
read as “accepts nothing”.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.request_shape.refresh_request_shapes(ids=None, , get_json=None, write=False, path=None)

`{endpoint_id: shape}` for `ids` (default: every catalogued model),
each fetched from fal. With `write`, each record of the catalogue
(`path`, default `falaw/data/models.json`) gets those fields; a field
left at its default (`None`, `False`, `image_size`) is dropped from
the record rather than written, as the catalogue writes defaults. A
retired endpoint (`None`) is left as it is. A schema that cannot be read
(a 429, a 5xx, a shape this module does not know) is never guessed: the
others are fetched (and written), then `RuntimeError` names each failure.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

### falaw.request_shape.request_shape(properties)

The record fields ([`SHAPE_FIELDS`](#falaw.request_shape.SHAPE_FIELDS)) an endpoint’s input properties
imply: their names (sorted), whether `negative_prompt` is one, the
`prompt`’s `maxLength` (`None` when it states none), and the size
input (`aspect_ratio` only when the model takes it and no `image_size`).

```pycon
>>> request_shape({"prompt": {}, "aspect_ratio": {}})["size_param"]
'aspect_ratio'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
