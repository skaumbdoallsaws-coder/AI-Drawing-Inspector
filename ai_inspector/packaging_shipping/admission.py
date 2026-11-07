"""Host-owned, expiring editor admissions and synchronous gateway mutation leases.

Renderer state is evidence, not identity or edit authority. A principal has one
selected editor; publishing another invalidates the previous admission before
checking the replacement. Host callers must drain gateway work before finish.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import secrets
import threading
import time
from typing import Annotated, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from .geometry import digest
from .permissions import EDIT, READ, permits
from .service import PackagingError, PackagingService


WORKFLOW = "packaging_shipping"
MAX_REVISION = 9007199254740991
_HOST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}")
DocumentId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
OpaqueId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{16,128}$")]
HostId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")]
Revision = Annotated[int, Field(strict=True, ge=0, le=MAX_REVISION)]


class EditorState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    document_id: DocumentId
    revision: Revision
    session_id: HostId
    conversation_id: HostId
    active_mode: Annotated[str, Field(min_length=1, max_length=64)]
    dirty: bool
    conflict: bool
    pending_operations: Annotated[int, Field(ge=0, le=1000)]


class EditorHeartbeat(EditorState):
    selection_id: OpaqueId


class EditorRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    selection_id: OpaqueId


def packaging_scope(principal: FacilityPrincipal) -> str:
    return digest({"tenant": principal.tenant_id, "sites": sorted(principal.allowed_site_ids), "workflow": WORKFLOW})


def _owner(principal):
    return principal.tenant_id, principal.principal_id


def _same_principal(left, right):
    return (isinstance(left, FacilityPrincipal) and isinstance(right, FacilityPrincipal)
            and left == right)


def _error(code, message, status=409):
    return PackagingError(code, message, status)


@dataclass
class _Editor:
    admission_id: str
    selection_id: str
    principal: FacilityPrincipal
    scope: str
    document_id: str
    revision: int
    session_id: str
    conversation_id: str
    expires_at: float
    revoked: bool = False
    started: bool = False
    terminal: bool = False
    turn: PackagingTurn | None = None


class PackagingAdmission:
    """One manager per host PackagingService, shared by HTTP and Sage runtime.

    ``principal_resolver`` passed to begin must freshly validate the authenticated
    host session on *every* invocation, and raise on disconnect/session expiry.
    It must be synchronous and thread-safe; never capture a normalized renderer
    principal or return a permanently cached authorization snapshot.
    Host authorization/session transitions must use transition_guard(), or revoke
    and await acknowledgement before exposing the transition to the editor.
    """

    def __init__(self, service: PackagingService, *, ttl_seconds=30, lock_timeout=2,
                 max_editors=256, max_turns=4096, clock: Callable[[], float] = time.monotonic):
        if (not isinstance(service, PackagingService) or not callable(clock)
                or type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 300
                or type(lock_timeout) not in (int, float) or not math.isfinite(lock_timeout) or not 0 < lock_timeout <= 10
                or type(max_editors) is not int or not 1 <= max_editors <= 4096
                or type(max_turns) is not int or not 1 <= max_turns <= 1000000):
            raise ValueError("Invalid packaging admission configuration.")
        self.service = service
        self.ttl_seconds, self.lock_timeout = float(ttl_seconds), float(lock_timeout)
        self.max_editors, self.max_turns, self._clock = max_editors, max_turns, clock
        self._lock = threading.RLock()
        self._editors: dict[str, _Editor] = {}
        self._selected: dict[tuple[str, str], str] = {}
        # No eviction: a replay must not become eligible after unrelated turns.
        self._used_turns: set[tuple] = set()

    @contextmanager
    def _lease(self):
        if not self._lock.acquire(timeout=self.lock_timeout):
            raise _error("editor_busy", "The packaging editor is completing another operation. Retry before transitioning.")
        try:
            yield
        finally:
            self._lock.release()

    def transition_guard(self):
        """Same bounded lease for host-owned role/session/disconnect changes."""
        return self._lease()

    def _now(self):
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise _error("editor_unavailable", "Packaging admission is unavailable.", 503)
        return value

    @staticmethod
    def _principal(principal):
        if not permits(principal, READ):
            raise _error("editor_not_authorized", "Your application role does not permit packaging admission.", 403)

    def _invalidate(self, editor):
        editor.revoked = True
        if editor.turn is not None:
            editor.turn.cancel_event.set()
        if self._selected.get(_owner(editor.principal)) == editor.admission_id:
            self._selected.pop(_owner(editor.principal), None)

    def _lookup(self, principal, admission_id):
        self._principal(principal)
        editor = self._editors.get(admission_id) if isinstance(admission_id, str) else None
        if editor is None or _owner(editor.principal) != _owner(principal):
            raise _error("editor_not_found", "Packaging editor admission was not found.", 404)
        if not _same_principal(editor.principal, principal):
            self._invalidate(editor)
            raise _error("editor_identity_changed", "Packaging authorization changed. Publish a fresh saved editor state.")
        self._live(editor)
        return editor

    def _live(self, editor):
        if (editor.revoked or self._editors.get(editor.admission_id) is not editor
                or self._selected.get(_owner(editor.principal)) != editor.admission_id):
            raise _error("editor_revoked", "Packaging editor admission is no longer active.")
        if self._now() >= editor.expires_at:
            self._invalidate(editor)
            raise _error("editor_expired", "Packaging editor admission expired. Publish a fresh saved editor state.")

    @staticmethod
    def _saved_state(state):
        if (state.active_mode != WORKFLOW or state.dirty is not False or state.conflict is not False
                or state.pending_operations != 0):
            raise _error("editor_not_saved", "Select a saved packaging document with no pending edits, conflicts or operations.")

    def _document_revision(self, editor):
        try:
            document = self.service.get(editor.scope, editor.document_id)
        except Exception:
            self._invalidate(editor)
            raise _error("editor_document_unavailable", "The admitted packaging document is unavailable.", 404) from None
        revision = document.get("revision")
        if document.get("id") != editor.document_id or type(revision) is not int or not 0 <= revision <= MAX_REVISION:
            self._invalidate(editor)
            raise _error("editor_document_unavailable", "The admitted packaging document is unavailable.", 404)
        return revision

    def _prune(self):
        now = self._now()
        for key, editor in list(self._editors.items()):
            if editor.revoked or now >= editor.expires_at:
                self._invalidate(editor)
                del self._editors[key]

    def _response(self, editor):
        return {"admission_id": editor.admission_id, "selection_id": editor.selection_id,
                "expires_in": max(0, editor.expires_at - self._now())}

    def publish(self, principal: FacilityPrincipal, state: EditorState | dict):
        with self._lease():
            self._principal(principal)
            prior_id = self._selected.get(_owner(principal))
            if prior_id is not None:
                self._invalidate(self._editors[prior_id])
            # A failed replacement must never leave the old selection admitted.
            try:
                state = EditorState.model_validate(state)
            except ValidationError:
                raise _error("editor_state_invalid", "The packaging editor state is invalid.", 400) from None
            self._saved_state(state)
            self._prune()
            if len(self._editors) >= self.max_editors:
                raise _error("editor_capacity", "Packaging editor admission capacity has been reached.", 503)
            editor = _Editor(secrets.token_urlsafe(32), "s_" + secrets.token_urlsafe(32), principal,
                             packaging_scope(principal), state.document_id, state.revision,
                             state.session_id, state.conversation_id, self._now() + self.ttl_seconds)
            if self._document_revision(editor) != state.revision:
                raise _error("revision_conflict", "The saved packaging revision changed. Reload before publishing admission.")
            self._editors[editor.admission_id] = editor
            self._selected[_owner(principal)] = editor.admission_id
            return self._response(editor)

    def heartbeat(self, principal: FacilityPrincipal, admission_id: str, state: EditorHeartbeat | dict):
        with self._lease():
            editor = self._lookup(principal, admission_id)
            if editor.terminal:
                raise _error("editor_turn_finished", "This packaging turn is finished. Publish a fresh saved editor state.")
            try:
                try:
                    state = EditorHeartbeat.model_validate(state)
                except ValidationError:
                    raise _error("editor_state_invalid", "The packaging heartbeat state is invalid.", 400) from None
                self._saved_state(state)
                if (state.selection_id != editor.selection_id or state.document_id != editor.document_id
                        or state.session_id != editor.session_id or state.conversation_id != editor.conversation_id):
                    raise _error("editor_selection_changed", "The packaging selection changed. Publish a fresh saved editor state.")
                if editor.turn is not None:
                    turn = editor.turn
                    turn._context_locked()
                    if not editor.revision <= state.revision <= turn._revision:
                        raise _error("revision_conflict", "The editor revision is not owned by this packaging turn.")
                elif state.revision != editor.revision or self._document_revision(editor) != editor.revision:
                    raise _error("revision_conflict", "The saved packaging revision changed. Reload before renewing admission.")
                editor.revision = state.revision
                editor.expires_at = self._now() + self.ttl_seconds
                return self._response(editor)
            except Exception:
                self._invalidate(editor)
                raise

    def revoke(self, principal: FacilityPrincipal, admission_id: str, state: EditorRevoke | dict):
        with self._lease():
            self._principal(principal)
            editor = self._editors.get(admission_id) if isinstance(admission_id, str) else None
            if editor is None or _owner(editor.principal) != _owner(principal):
                raise _error("editor_not_found", "Packaging editor admission was not found.", 404)
            # Revocation remains possible after expiry or a role/site change.
            self._invalidate(editor)
            try:
                state = EditorRevoke.model_validate(state)
            except ValidationError:
                raise _error("editor_state_invalid", "The packaging revoke state is invalid.", 400) from None
            if state.selection_id != editor.selection_id:
                raise _error("editor_selection_changed", "The packaging selection changed.")
            return {"admission_id": editor.admission_id, "selection_id": editor.selection_id, "expires_in": 0}

    def reference(self, principal: FacilityPrincipal, admission_id: str):
        """Read a memory binding without consuming, renewing or acknowledging it."""
        with self._lease():
            editor = self._lookup(principal, admission_id)
            if editor.terminal:
                try:
                    turn = editor.turn
                    if turn is None or not turn._finished or turn.cancel_event.is_set():
                        raise _error("editor_turn_cancelled", "This packaging turn is no longer active.")
                    turn._principal_locked()
                    expected = turn._revision
                except Exception:
                    self._invalidate(editor)
                    raise
            elif editor.turn is not None:
                editor.turn._context_locked()
                expected = editor.turn._revision
            else:
                expected = editor.revision
            revision = self._document_revision(editor)
            if revision != expected:
                self._invalidate(editor)
                raise _error("revision_conflict", "The saved packaging revision changed outside this turn.")
            self._live(editor)
            if editor.turn is not None and editor.turn.cancel_event.is_set():
                self._invalidate(editor)
                raise _error("editor_turn_cancelled", "This packaging turn is no longer active.")
            return {"document_id": editor.document_id, "revision": revision, "selection_id": editor.selection_id,
                    "session_id": editor.session_id, "conversation_id": editor.conversation_id}

    def begin(self, principal: FacilityPrincipal, admission_id: str, *, principal_resolver: Callable[[], FacilityPrincipal],
              session_id: str, conversation_id: str, turn_id: str, direct_edit_authorized=False,
              cancel_event: threading.Event | None = None):
        if (not callable(principal_resolver) or type(direct_edit_authorized) is not bool
                or not all(isinstance(value, str) and _HOST_ID.fullmatch(value) for value in (session_id, conversation_id, turn_id))
                or (cancel_event is not None and not isinstance(cancel_event, threading.Event))):
            raise _error("editor_turn_invalid", "A valid host packaging turn binding is required.", 400)
        with self._lease():
            editor = self._lookup(principal, admission_id)
            if session_id != editor.session_id or conversation_id != editor.conversation_id:
                self._invalidate(editor)
                raise _error("editor_identity_changed", "The admitted host session or conversation changed.")
            if editor.started:
                raise _error("editor_turn_active", "This editor admission has already been consumed by a turn.")
            if direct_edit_authorized and not permits(principal, EDIT):
                raise _error("editor_edit_denied", "Direct packaging edits are not authorized for this principal.", 403)
            key = (_owner(principal), session_id, conversation_id, turn_id)
            if key in self._used_turns:
                raise _error("editor_turn_replayed", "This host turn was already admitted. Reconcile its receipts before retrying.")
            if len(self._used_turns) >= self.max_turns:
                raise _error("editor_capacity", "Packaging turn admission capacity has been reached.", 503)
            turn = PackagingTurn(self, editor, principal_resolver, session_id, conversation_id, turn_id,
                                 direct_edit_authorized, cancel_event if cancel_event is not None else threading.Event())
            editor.turn = turn
            try:
                turn._context_locked()
            except Exception:
                self._invalidate(editor)
                editor.turn = None
                raise
            editor.started = True
            self._used_turns.add(key)
            return turn

    admit_turn = begin


class PackagingTurn:
    """Host-only handle; supply its callbacks to PackagingGateway.

    ``with admission.begin(...) as turn:`` releases in all exit paths. Call
    ``cancel()`` for cancellation and ``finish()`` after draining the gateway.
    Cancellation cannot undo a synchronous transaction already entered.
    """

    def __init__(self, manager, editor, current_principal, session_id, conversation_id, turn_id, direct_edit, cancel_event):
        self._manager, self._editor, self._current_principal = manager, editor, current_principal
        self._session_id, self._conversation_id, self.turn_id = session_id, conversation_id, turn_id
        self._direct_edit, self.cancel_event = direct_edit, cancel_event
        self._revision = self.initial_revision = editor.revision
        self._mutation_thread = None
        self._finished = False

    @property
    def admission_id(self):
        return self._editor.admission_id

    @property
    def selection_id(self):
        return self._editor.selection_id

    @property
    def document_id(self):
        return self._editor.document_id

    def _context_locked(self):
        manager, editor = self._manager, self._editor
        manager._live(editor)
        if self._finished:
            raise _error("editor_turn_finished", "This packaging turn is finished and cannot execute more tools.")
        try:
            if editor.turn is not self or self.cancel_event.is_set():
                raise _error("editor_turn_cancelled", "This packaging turn is no longer active.")
            principal = self._principal_locked()
            actual = manager._document_revision(editor)
            upper = self._revision + (self._mutation_thread == threading.get_ident())
            if not self._revision <= actual <= upper or not self.initial_revision <= editor.revision <= self._revision:
                raise _error("revision_conflict", "The saved packaging revision changed outside this turn.")
            # Recheck cancellation/expiry after host callbacks and database work.
            manager._live(editor)
            if self.cancel_event.is_set():
                raise _error("editor_turn_cancelled", "This packaging turn is no longer active.")
            from ai_inspector.codex_runtime.packaging_tools import PackagingContext
            return PackagingContext(principal=principal, session_id=self._session_id, conversation_id=self._conversation_id,
                                    selection_id=editor.selection_id, document_id=editor.document_id, revision=editor.revision,
                                    active_mode=WORKFLOW, dirty=False, conflict=False, pending_operations=0,
                                    direct_edit_authorized=self._direct_edit)
        except Exception:
            manager._invalidate(editor)
            raise

    def _principal_locked(self):
        try:
            principal = self._current_principal()
        except Exception:
            raise _error("editor_identity_changed", "Packaging host authorization is no longer available.") from None
        if (not _same_principal(principal, self._editor.principal) or not permits(principal, READ)
                or (self._direct_edit and not permits(principal, EDIT))
                or packaging_scope(principal) != self._editor.scope):
            raise _error("editor_identity_changed", "Packaging host authorization changed.")
        return principal

    def current_context(self):
        with self._manager._lease():
            return self._context_locked()

    @contextmanager
    def mutation_guard(self):
        manager = self._manager
        with manager._lease():
            self._context_locked()
            if not self._direct_edit:
                raise _error("editor_edit_denied", "This packaging turn is read-only.", 403)
            if self._mutation_thread is not None:
                raise _error("editor_busy", "A packaging mutation lease is already active.")
            self._mutation_thread = threading.get_ident()
            try:
                yield
                self._context_locked()
                revision = manager._document_revision(self._editor)
                if not self._revision <= revision <= self._revision + 1:
                    raise _error("revision_conflict", "The saved packaging revision changed outside this turn.")
                self._revision = revision
            except BaseException:
                manager._invalidate(self._editor)
                raise
            finally:
                self._mutation_thread = None

    def cancel(self):
        # Immediate cancellation intent also works when another thread holds the
        # lease. A failed lock acquisition is NOT a transition acknowledgement.
        self.cancel_event.set()
        with self._manager._lease():
            self._manager._invalidate(self._editor)

    def finish(self, *, keep_reference=False):
        """Finish after drain; keep_reference is for verified normal success only.

        A preserved terminal reference cannot renew or authorize tools. Repeated
        cleanup is idempotent, including close after a successful preservation.
        Call cancel (not close) to invalidate a previously completed reference.
        """
        if type(keep_reference) is not bool:
            raise ValueError("keep_reference must be a boolean.")
        with self._manager._lease():
            if self._finished:
                return
            if keep_reference:
                try:
                    self._context_locked()
                    if self._mutation_thread is not None:
                        raise _error("editor_busy", "Drain packaging mutations before finishing the turn.")
                    if self._manager._document_revision(self._editor) != self._revision:
                        raise _error("revision_conflict", "The saved packaging revision changed outside this turn.")
                    self._manager._live(self._editor)
                    if self.cancel_event.is_set():
                        raise _error("editor_turn_cancelled", "This packaging turn is no longer active.")
                    self._editor.terminal = True
                except Exception:
                    self._manager._invalidate(self._editor)
                    raise
            else:
                self.cancel_event.set()
                self._manager._invalidate(self._editor)
                if self._editor.turn is self:
                    self._editor.turn = None
            self._finished = True

    close = finish

    def __enter__(self):
        try:
            self.current_context()
            return self
        except BaseException:
            self.finish()
            raise

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.cancel()
        self.finish()
        return False
