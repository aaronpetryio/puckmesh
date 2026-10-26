"""One module per API endpoint.

Each exposes NAME and fetch(client, ...) -> (response, params), plus helpers that read
its response. Knowledge of a response's shape lives only in its endpoint's module.
"""
