# The OpenAPI fixtures

These files are the input of `tests/test_api_openapi.py`.

- `tiny_app.py` is a small FastAPI app. `tiny.json` is its document, with the file and line of each
  route. `scripts/openapi_cases.py` writes `tiny.json` again.
- `tiny_setup.py` holds the setup functions that the tests name in `setup:`.
- `handmade-3.0.yaml` is a hand-made OpenAPI 3.0 document. `swagger-2.0.json` is a Swagger 2.0 document,
  which smalldocs refuses.
- `petstore.yaml`, `petstore-expanded.yaml`, `callback-example.yaml` and `webhook-example.yaml` come from
  the examples of the OpenAPI Initiative, at <https://github.com/OAI/learn.openapis.org>. They are under
  the Creative Commons Attribution 4.0 International license (CC BY 4.0). We did not change them.
