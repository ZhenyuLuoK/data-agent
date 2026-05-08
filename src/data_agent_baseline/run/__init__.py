"""``data_agent_baseline.run`` package.

Submodules are imported lazily on demand (``from data_agent_baseline.run.runner
import ...``) rather than re-exported here. This keeps the lightweight modules
(``scoring``, ``vote``, ``table_signature``) usable in environments that don't
have the heavy agent dependencies (``langgraph``, ``matplotlib``) installed —
e.g. when only the offline scorer is needed.
"""
