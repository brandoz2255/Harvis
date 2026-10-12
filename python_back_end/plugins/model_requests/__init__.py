"""Request-a-model queue: signed-in users ask for a model, the admin approves or denies.

Approving only records the decision; the admin still downloads the model through the
existing cookbook download. See ``routes.py`` for the contract and the spam limits.
"""
