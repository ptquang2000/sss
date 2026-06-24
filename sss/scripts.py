"""ScriptRunner: interpret declarative ``pre_sync`` / ``post_sync`` step lists.

Each step is ``{"op": <name>, "args": {...}}``. ``op`` is constrained to the
fixed primitive vocabulary; anything else is rejected (the no-arbitrary-code
guarantee). Steps are dispatched to the session's primitives in list order.
"""

from typing import List

from .exceptions import SssError

# op name -> (session attribute path, method). The fixed vocabulary; this is
# the *only* set of operations a declarative script may invoke.
_VOCABULARY = {
    "stop_service": lambda s, a: s.service.stop(**a),
    "start_service": lambda s, a: s.service.start(**a),
    "stop_process": lambda s, a: s.process.stop(**a),
    "start_process": lambda s, a: s.process.start(*a.pop("args", []), **a),
    "remove_files": lambda s, a: s.files.remove(**a),
    "delete_files": lambda s, a: s.files.delete(**a),
    "sync": lambda s, a: s.sync.run(**a),
    "exec": lambda s, a: s.exec(**a),
}

VALID_OPS = frozenset(_VOCABULARY)


class ScriptRunner:
    def __init__(self, session):
        self._session = session

    @staticmethod
    def validate(steps: List[dict]) -> None:
        """Raise if any step names an op outside the fixed vocabulary."""
        for i, step in enumerate(steps or []):
            if not isinstance(step, dict) or "op" not in step:
                raise SssError(f"Step {i} is malformed (expected {{'op': ...}}): {step!r}")
            op = step["op"]
            if op not in _VOCABULARY:
                raise SssError(
                    f"Unknown op '{op}' in step {i}. Allowed: {sorted(VALID_OPS)}"
                )

    def run(self, steps: List[dict]) -> List[dict]:
        """Validate, then dispatch each step to its primitive in order."""
        self.validate(steps)
        results = []
        for step in steps or []:
            op = step["op"]
            args = dict(step.get("args", {}))
            outcome = _VOCABULARY[op](self._session, args)
            results.append({"op": op, "result": outcome})
        return results
