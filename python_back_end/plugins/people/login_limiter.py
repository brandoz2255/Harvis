"""A per-account limit on password guesses, in front of both sign-in routes.

nginx limits sign-in per source address, which a tester with a few addresses
walks around. This counts guesses per email instead: ten wrong passwords for one
address inside 15 minutes lock that address out for 15 minutes with a 429, whoever
asks and whatever address they come from. A locked request still spends one bcrypt
check, so the refusal is not faster than a wrong password.

It sits around the routes (an ASGI middleware that reads the email from the JSON
body and watches the status that comes back) so ``/api/auth/login`` and
``/api/v1/auths/signin`` share one counter without either handler knowing. The
counters live in this process: a restart clears them, which is the operator's way
out of a lockout someone caused on purpose.
"""
from __future__ import annotations

import json
import math
import time
from collections import OrderedDict, deque

from passlib.context import CryptContext
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
MAX_TRACKED = 10_000
MAX_BODY = 16 * 1024
SIGNIN_PATHS = frozenset({"/api/auth/login", "/api/v1/auths/signin"})
LOCKED_MESSAGE = "Too many failed sign-in attempts for this account. Try again in 15 minutes."

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_dummy_hash: str | None = None


class _Account:
    __slots__ = ("attempts", "locked_until")

    def __init__(self) -> None:
        self.attempts: deque[float] = deque()
        self.locked_until = 0.0


class LoginLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._accounts: "OrderedDict[str, _Account]" = OrderedDict()

    @staticmethod
    def key(email: str) -> str:
        return email.strip().lower()

    def _account(self, key: str) -> _Account:
        acct = self._accounts.get(key)
        if acct is None:
            while len(self._accounts) >= MAX_TRACKED:
                self._accounts.popitem(last=False)
            acct = self._accounts[key] = _Account()
        else:
            self._accounts.move_to_end(key)
        return acct

    def begin(self, email: str) -> int:
        """Count one attempt that is about to be made. Returns 0 to let it run, or the
        seconds the account stays locked. Counting before the answer means a burst of
        parallel guesses cannot all slip in ahead of the first refusal."""
        key, now = self.key(email), self._clock()
        acct = self._account(key)
        if acct.locked_until > now:
            return max(1, math.ceil(acct.locked_until - now))
        while acct.attempts and now - acct.attempts[0] > WINDOW_SECONDS:
            acct.attempts.popleft()
        if len(acct.attempts) >= MAX_FAILURES:
            acct.locked_until = now + LOCKOUT_SECONDS
            acct.attempts.clear()
            return LOCKOUT_SECONDS
        acct.attempts.append(now)
        return 0

    def succeeded(self, email: str) -> None:
        self._accounts.pop(self.key(email), None)

    def refund(self, email: str) -> None:
        """The attempt did not turn out to be a wrong password (blocked account, server error)."""
        acct = self._accounts.get(self.key(email))
        if acct and acct.attempts:
            acct.attempts.pop()

    def failed(self, email: str) -> None:
        acct = self._accounts.get(self.key(email))
        if acct and len(acct.attempts) >= MAX_FAILURES:
            acct.locked_until = self._clock() + LOCKOUT_SECONDS
            acct.attempts.clear()

    def reset(self) -> None:
        self._accounts.clear()


limiter = LoginLimiter()


def _burn_bcrypt() -> None:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _pwd.hash("harvis-dummy-password")
    try:
        _pwd.verify("not-the-password", _dummy_hash)
    except Exception:  # noqa: BLE001
        pass


async def _read_body(receive: Receive) -> tuple[bytes, list[Message]] | None:
    """The whole request body, or None when it is bigger than any sign-in form."""
    chunks: list[Message] = []
    body = b""
    while True:
        message = await receive()
        chunks.append(message)
        if message["type"] != "http.request":
            return body, chunks
        body += message.get("body", b"")
        if len(body) > MAX_BODY:
            return None
        if not message.get("more_body"):
            return body, chunks


def _email_in(body: bytes) -> str | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    email = data.get("email") if isinstance(data, dict) else None
    return email if isinstance(email, str) and email.strip() else None


class LoginThrottleGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or scope.get("path") not in SIGNIN_PATHS):
            await self.app(scope, receive, send)
            return
        read = await _read_body(receive)
        if read is None:
            await JSONResponse({"detail": "Request too large."}, status_code=413)(scope, receive, send)
            return
        body, chunks = read
        email = _email_in(body)
        if email is None:
            # Nothing to count against; the route answers 422 for a body like this.
            replay = iter(chunks)

            async def replay_receive() -> Message:
                return next(replay, None) or await receive()

            await self.app(scope, replay_receive, send)
            return
        wait = limiter.begin(email)
        if wait:
            await run_in_threadpool(_burn_bcrypt)
            await JSONResponse({"detail": LOCKED_MESSAGE}, status_code=429,
                               headers={"Retry-After": str(wait)})(scope, receive, send)
            return

        replay = iter(chunks)

        async def replay_receive() -> Message:
            return next(replay, None) or await receive()

        outcome: dict[str, int] = {}

        async def watching_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                outcome["status"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, replay_receive, watching_send)
        except BaseException:
            limiter.refund(email)
            raise
        status = outcome.get("status", 500)
        if status == 401:
            limiter.failed(email)
        elif 200 <= status < 300:
            limiter.succeeded(email)
        else:
            limiter.refund(email)
