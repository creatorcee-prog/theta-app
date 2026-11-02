"""Route(): central model selection (Stage 4) and its contract.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Stage 4 P1 interface: central model selection (route()).
# P1 interface PR ONLY: this section ADDS a selection function that is
# side-effect-free apart from one diagnostic line.
# No production path calls route() yet, so reverting this section (plus
# its tests) changes zero behavior. Call-site migration PRs will call
# route() one entry point at a time; the allchat migration in particular
# must NOT start until this interface contract is reviewed (D5 hinge
# below).
#
# Contract (read before migrating a call site):
# - route() SELECTS; it never calls a model, never loops tools (D1:
#   single-pass preserved), never reads llm:last_selection (that record
#   is a most-recent snapshot, never request-level attribution or
#   billing evidence), and never writes llm:last_selection either
#   (selection is not answering; writing it would be false
#   attribution). It emits one model.selected diag line (same fields
#   as P0's _note_model_selection, via="route") so selections are
#   observable in logs.
# - Inputs are exactly: role, agent, entry_point, desk_up, master_up,
#   plus ROUTE_* environment variables read at CALL time. Nothing
#   else. In particular route() never reads TIER_LLM, FALLBACK_LLM,
#   DESK_MODEL, LOW_BRAIN_MODEL, or MASTER_MONTHLY_CAP_USD, so a
#   chat Approve change to a SETTABLE value cannot move route()
#   decisions (D6). desk_up / master_up are caller-supplied state:
#   migration PRs pass desk_on() / master_ready() (or their pure
#   equivalents where a site must avoid master_ready()'s cap-notify
#   side effect). Both are REQUIRED
#   keywords: there is no omitted-means-False, so no call site can
#   silently assume desk-off / master-not-ready, and route() never
#   performs a live desk_on() / master_ready() lookup itself.
# - Defaults are literals equal to the code's unset-env defaults. If
#   an upstream default changes, update ROUTE_DEFAULTS deliberately
#   in a migration PR; the P0 baseline tests pin legacy behavior, so
#   drift shows up there first.
# - Config precedence: ROUTE_<ROLE>_PROVIDER + ROUTE_<ROLE>_MODEL
#   (a complete pair) wins; otherwise the literal default. A half
#   pair, an unknown provider, or an empty model raises
#   RouteConfigError — never a silent fallback or silent default.
#   SETTABLE values do not leak into selections (tested).
# - Tier fallbacks keep the legacy shape: provider fixed per tier,
#   model overridable via ROUTE_<ROLE>_FALLBACK_MODEL, and "off"
#   suppresses that role's fallback step (mirrors
#   MINER/MANAGER/LOW_BRAIN_FALLBACK_MODEL="off" in FALLBACK_LLM,
#   where an "off" fallback is skipped and the borrow walk still
#   runs). route() does NOT read the legacy *_FALLBACK_MODEL vars:
#   a migration PR must translate a legacy "off" to the matching
#   ROUTE_*_FALLBACK_MODEL="off", or the migrated path regains a
#   fallback the operator turned off. There is no master/desk
#   fallback var: the master path falls back to the low_brain
#   stand-in chain, and the desk path falls back to the low_brain
#   chain.
# - Fallback-off IS modeled (see above). The one thing route() does
#   not do is read the legacy *_FALLBACK_MODEL vars — translation
#   is a migration-PR obligation, flagged in the inventory table.
# - fallback_off (migration #1 contract extension): route(...,
#   fallback_off) suppresses the fallback step for the named roles
#   even when their ROUTE_*_FALLBACK_MODEL is set. It exists so a
#   migrated call site can translate a legacy FALLBACK_LLM "off"
#   without a production env change; it never reads legacy vars
#   itself, and the caller computes it from FALLBACK_LLM.
# - DeepSeek is ABSENT from ROUTE_PROVIDERS by design (D2:
#   probe-only). A verified provider plugs in here later by adding
#   its name to ROUTE_PROVIDERS plus its default model id — only
#   after provider, identifier, endpoint, credentials, tool-call
#   compliance, limits, and pricing are verified.
#
# Concise call-site inventory (full table with lines + behavior in
# the P1 interface PR body; all sites NOT migrated — route() is
# uncalled):
# - Selection logic: llm_chat (tier chain + retry + tier fallback +
#   borrow), desk_chat (desk path), claude_chat (Anthropic SDK
#   direct), gemini_search (native search API, own budget),
#   borrow_help (upward walk), room_for (capacity pre-check),
#   master_ready (key + cap gate), desk_on (desk state).
# - Tier callers (each picks a tier, then llm_chat/desk_chat):
#   desk_reply/ask_as, allchat_reply (first turn + SEARCH second
#   turn), answer_with_search, pick_responders (router),
#   round_summary, summarize, master_work, _post_leads,
#   plan_project, plus background jobs (gym_ask, _triage_escalations,
#   _theta_decisions, _round_theta, send_digest, _round_news,
#   _lenz_pitch, _round_remi_calendar, stock_week_note, file_issue,
#   story_brief, condense_titles, acknowledge_order, job_query,
#   classify_mail, draft_reply, handle).
# - Bypass / out of scope for route(): _search_web/_work (project
#   search, Gemini-only per D10 until its migration PR), james_ask
#   (external Garage Gym owns prompt + model, D11), run_bench
#   (diagnostic, DESK_MODEL direct by design), vision gating
#   (theta + master_ready only), quick_reply / remi_quick_reply
#   (no model by design), adzuna_jobs / usajobs_jobs (keyed HTTP
#   APIs, not models).
# - D5 hinge (flipped by migration #2): DESK_ENTRY_POINTS includes
#   "allchat", so Mistral's allchat first turn now runs the desk path
#   (desk_chat), NOT the tier path. Desk-off behavior is unchanged:
#   the desk path with desk_up False IS the low_brain chain.
# - MIGRATED (migration #1): _triage_escalations' low_brain call now
#   goes through route() (primary + tier-fallback overrides into
#   llm_chat); every other site still runs its legacy path.
# - MIGRATED (migration #2): Mistral's allchat first turn now goes
#   through desk_chat, driven by route() (desk + low_brain overrides
#   into desk_chat); every other allchat agent still runs its legacy
#   llm_chat tier path, and the SEARCH second turn is untouched.
# - (Migrations #3-#5: send_digest, classify_mail, _lenz_pitch; see
#   their call sites.)
# - MIGRATED (migration #6): every desk_chat call for Mistral now takes
#   its models from route() through desk_route(): desk_reply (entry
#   "desk"), the SEARCH turn in answer_with_search ("search"), and
#   round_summary ("round"), plus #2's allchat turn ("allchat", pure).
#   desk_up keeps the legacy state (DESK_MODEL "off", master_ready()).
# - MIGRATED (migration #7): borrow_help's candidates come from
#   _route_primary / _route_fallback; desk_on() stays the desk state
#   and a legacy FALLBACK_LLM "off" still skips that step. The legacy
#   model vars these sites no longer read (DESK_MODEL's model id,
#   LOW_BRAIN_MODEL, MINER/MANAGER_MODEL, *_FALLBACK_MODEL) are flagged
#   by the checkup (route_drift()) when they differ from route().


class RouteConfigError(ValueError):
    """route() configuration is invalid: half a pair, unknown provider,
    or empty model. Raised, never silently defaulted."""


ROUTE_PROVIDERS = {"groq", "gemini", "anthropic", "local", "deepseek"}  # local: your PC (LOCAL_LLM_URL); deepseek: Stage 8.1

# Literal current-behavior defaults (see contract above: NOT read from
# SETTABLE-managed vars, so Approve taps cannot move route()).
ROUTE_DEFAULTS = {
    "miner": ("groq", "openai/gpt-oss-20b"),
    "manager": ("groq", "openai/gpt-oss-120b"),
    "low_brain": ("gemini", "gemini-3.8-flash"),
    "master": ("anthropic", "claude-opus-5-5"),
    "desk": ("anthropic", "claude-haiku-5-5"),
}
ROUTE_FALLBACK_DEFAULTS = {
    "miner": ("groq", "openai/gpt-oss-120b"),
    "manager": ("gemini", "gemini-3.8-flash"),
    "low_brain": ("groq", "openai/gpt-oss-120b"),
}
ROUTE_CONFIG_VARS = {
    "miner": ("ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL"),
    "manager": ("ROUTE_MANAGER_PROVIDER", "ROUTE_MANAGER_MODEL"),
    "low_brain": ("ROUTE_LOW_BRAIN_PROVIDER", "ROUTE_LOW_BRAIN_MODEL"),
    "master": ("ROUTE_MASTER_PROVIDER", "ROUTE_MASTER_MODEL"),
    "desk": ("ROUTE_DESK_PROVIDER", "ROUTE_DESK_MODEL"),
}
ROUTE_ENTRY_POINTS = {"desk", "allchat", "router", "round", "search",
                      "project", "summary", "bench", "other"}
DESK_ENTRY_POINTS = {"desk", "round", "search", "allchat"}  # D5 hinge flipped by migration #2: allchat now takes the desk path.

# Fallback models: legacy shape (provider fixed per tier, model
# overridable, "off" suppresses the step). No master/desk fallback
# vars: the master path falls back to the low_brain stand-in chain,
# and the desk path falls back to the low_brain chain.
ROUTE_FALLBACK_VARS = {
    "miner": "ROUTE_MINER_FALLBACK_MODEL",
    "manager": "ROUTE_MANAGER_FALLBACK_MODEL",
    "low_brain": "ROUTE_LOW_BRAIN_FALLBACK_MODEL",
}


def _route_fallback(role, off=False):
    """(provider, model) for `role`'s tier fallback, or None when `off`
    is true or its ROUTE_*_FALLBACK_MODEL is "off". Unset/empty means the
    literal default; any other value replaces the model only (provider stays
    the tier's default fallback provider, as in FALLBACK_LLM). Reads
    env at call time."""
    if off:
        return None
    var = ROUTE_FALLBACK_VARS[role]
    model = (os.environ.get(var) or "").strip()
    if model == "off":
        return None
    if model:
        return (ROUTE_FALLBACK_DEFAULTS[role][0], model)
    return ROUTE_FALLBACK_DEFAULTS[role]


def _route_primary(role):
    """(provider, model) for `role`: ROUTE_* override pair, else the
    literal default. Raises RouteConfigError on a half pair, an
    unknown provider, or an empty model. Reads env at call time."""
    pvar, mvar = ROUTE_CONFIG_VARS[role]
    provider = (os.environ.get(pvar) or "").strip()
    model = (os.environ.get(mvar) or "").strip()
    if bool(provider) != bool(model):
        raise RouteConfigError(
            f"route {role}: set both {pvar} and {mvar}, or neither (half a pair)")
    if provider:
        if provider not in ROUTE_PROVIDERS:
            raise RouteConfigError(
                f"route {role}: unknown provider {provider!r} "
                f"(groq, gemini, anthropic, local, deepseek)")
        return (provider, model)
    return ROUTE_DEFAULTS[role]


def _route_candidates(role, desk_up, master_up, prim, fallback):
    """Ordered, deduped [(provider, model)] for a tier path, following
    llm_chat's chain: primary, one tier fallback, then the borrow walk
    (_HELP_UP: miner -> manager -> low_brain; low_brain borrows nothing).
    A None fallback (ROUTE_*_FALLBACK_MODEL="off") skips that step;
    the borrow walk still runs. The master model never appears in any
    borrow walk (never-Theta): any candidate equal to the resolved
    master primary is dropped unless it IS the master primary of a
    master_up call."""
    master_pair = prim["master"]
    if role == "miner":
        chain = [prim["miner"], fallback["miner"]]
        if desk_up:
            chain.append(prim["desk"])
        chain += [prim["manager"], fallback["manager"],
                  prim["low_brain"], fallback["low_brain"]]
    elif role == "manager":
        chain = ([prim["desk"]] if desk_up else []) + [
            prim["manager"], fallback["manager"],
            prim["low_brain"], fallback["low_brain"]]
    elif role == "low_brain":
        chain = [prim["low_brain"], fallback["low_brain"]]
    else:  # master: Opus, then the low_brain stand-in chain
        chain = [prim["master"], prim["low_brain"], fallback["low_brain"]]
    out = []
    for pair in chain:
        if pair is not None and pair not in out:
            out.append(pair)
    if not (role == "master" and master_up):
        out = [pair for pair in out if pair != master_pair]
    if not out:
        raise RouteConfigError(f"route {role}: no usable candidate (overrides deduped everything away)")
    return out


def route(role, agent=None, entry_point=None, *, desk_up, master_up, fallback_off=()):
    """Central model selection (Stage 4 P1 interface). Side-effect-free
    apart from diagnostics: selects, never calls a model, never loops
    tools, never reads or writes llm:last_selection, never touches the
    store. Its single diagnostic effect is one model.selected diag line
    (via="route").

    role: one of TIERS (miner, manager, low_brain, master).
    agent: agent id for the DESK check (None = no agent context).
    entry_point: one of ROUTE_ENTRY_POINTS (None = generic tier path).
    desk_up / master_up: caller-supplied state (migration PRs pass
    desk_on() / master_ready(), or their pure equivalents where a site
    must avoid master_ready()'s cap-notify side effect); omitted is impossible here — both
    are required keywords, so no hidden live lookup exists.

    Returns a dict: role, agent, entry_point, path ("desk" or "tier"),
    tier (telemetry label, matching today's _note behavior: desk path
    notes under "low_brain"; master-not-ready notes under "low_brain"
    as the stand-in), desk_up, master_up, primary {provider, model},
    fallbacks [{provider, model}], candidates (primary + fallbacks,
    in try order), stand_in (True when the primary itself is the
    low_brain stand-in: master role with master_up False), policy
    (retry/fallback/borrow rules the executor must honor), budget
    (cap info for the migrator; route() enforces nothing).

    Desk path (agent == DESK and entry_point in DESK_ENTRY_POINTS)
    follows desk_chat: Haiku while desk_up, else the low_brain chain.
    Every other combination follows the tier path. Since migration #2
    (D5), agent == DESK with entry_point == "allchat" takes the desk
    path: Mistral's allchat first turn unifies with her desk replies.
    Desk path takes precedence over role: agent == DESK at a desk
    entry point follows the desk path even if role == "master"
    (migration PRs must never pass role="master" with agent=DESK;
    Mistral never answers as Theta, and the desk path drops the
    master pair unconditionally). A ROUTE_*_FALLBACK_MODEL of "off"
    suppresses that role's fallback step; the borrow walk is
    unaffected.
    fallback_off: optional roles whose fallback step is suppressed
    regardless of env (explicit caller override, wins over
    ROUTE_*_FALLBACK_MODEL). Migration #1 uses it to translate a
    legacy FALLBACK_LLM "off" with zero production env change;
    default empty means env behavior. Unknown roles raise
    RouteConfigError.
    """
    if role not in TIERS:
        raise RouteConfigError(f"unknown route role {role!r} (miner, manager, low_brain, master)")
    if agent is not None and agent not in AGENTS:
        raise RouteConfigError(f"unknown route agent {agent!r}")
    if entry_point is not None and entry_point not in ROUTE_ENTRY_POINTS:
        raise RouteConfigError(f"unknown route entry_point {entry_point!r}")
    off_roles = set(fallback_off or ())
    bad_off = off_roles - set(ROUTE_FALLBACK_VARS)
    if bad_off:
        raise RouteConfigError(f"unknown fallback_off role(s) {sorted(bad_off)} (miner, manager, low_brain)")
    prim = {}
    for r in ("miner", "manager", "low_brain", "master", "desk"):
        prim[r] = _route_primary(r)
    fallback = {r: _route_fallback(r, r in off_roles) for r in ("miner", "manager", "low_brain")}
    desk_path = agent == DESK and entry_point in DESK_ENTRY_POINTS
    if desk_path:
        if desk_up:
            cands = [prim["desk"], prim["low_brain"], fallback["low_brain"]]
        else:
            cands = [prim["low_brain"], fallback["low_brain"]]
        # The desk path never answers as Theta: drop the master pair
        # unconditionally (desk_chat never calls the master model,
        # even under overrides). An emptied list is a configuration
        # error, not an IndexError at primary = cands[0].
        out_cands = []
        for pair in cands:
            if pair is not None and pair != prim["master"] and pair not in out_cands:
                out_cands.append(pair)
        if not out_cands:
            raise RouteConfigError("route desk path: no usable candidate (overrides deduped everything away)")
        cands = out_cands
        path, tele_tier, stand_in = "desk", "low_brain", False
    elif role == "master":
        cands = _route_candidates("master", desk_up, master_up, prim, fallback)
        path, tele_tier = "tier", "master" if master_up else "low_brain"
        stand_in = not master_up
    else:
        cands = _route_candidates(role, desk_up, master_up, prim, fallback)
        path, tele_tier, stand_in = "tier", role, False
    primary = cands[0]
    if role == "master":
        budget = {"scope": "master-monthly", "default_cap_usd": 15.0, "hard_ceiling": False,
                  "enforced_by": "master_ready (legacy path; route() neither reads nor enforces the live cap)",
                  "note": "Hub-counted spend; cross-instance enforcement unverified (D4) — not a guaranteed hard ceiling."}
    else:
        budget = {"scope": None,
                  "note": "No monthly cap for this role; Groq room / Gemini cooldown checks live in the executor (room_for), not in route()."}
    decision = {
        "role": role, "agent": agent, "entry_point": entry_point, "path": path,
        "tier": tele_tier, "desk_up": desk_up, "master_up": master_up,
        "primary": {"provider": primary[0], "model": primary[1]},
        "fallbacks": [{"provider": p, "model": m} for p, m in cands[1:]],
        "candidates": [{"provider": p, "model": m} for p, m in cands],
        "stand_in": stand_in,
        "policy": {
            "retries": 1,
            "retry_delay_s": LLM_RETRY_DELAY,
            "retry_rule": "primary only; retryable and not timed_out (429s count as timed_out and skip the retry); non-retryable raises at once",
            "room_precheck": "executor-side: skip candidates failing room_for (cooling/Groq room); route() does not evaluate room state",
            "tried_set": "executor tries each candidate at most once, in listed order",
            "borrow": role in ("miner", "manager"),
            "single_pass": True,
        },
        "budget": budget,
    }
    _diag("model.selected", tier=tele_tier, provider=primary[0], model=primary[1], via="route", reason="")
    return decision


def llm_chat(tier, messages, max_tokens=800, primary=None, fallback=None):
    """One chat-completion call for `tier`; returns the reply text.
    Master is Claude while it's connected and under its monthly cap;
    otherwise the low brain answers for it.
    A busy or down provider gets one quick retry (not after a timeout),
    then the tier's fallback model on the other provider answers.
    primary/fallback (migration #1): optional route() values for this
    call. primary replaces TIER_LLM[t] for the primary step; fallback
    replaces FALLBACK_LLM[t] for the tier-fallback step, or "off" to
    suppress it. None means the legacy lookup. Desk-first, master,
    borrow, retry, room, key and error handling are unchanged; only
    the two values come from route().
    An explicitly set ROUTE_<TIER>_PROVIDER + _MODEL (or
    ROUTE_<TIER>_FALLBACK_MODEL) also fills in for every unmigrated
    caller of that tier, so one setting moves the whole tier (e.g. the
    miners onto your PC). Unset, the legacy lookup is unchanged."""
    if tier == "master" and master_ready():
        try:
            text = claude_chat(messages, max_tokens)
            _note_model_selection("master", "anthropic", MASTER_MODEL_ID, "master")
            return text
        except LLMError as e:  # Theta still answers, on the stand-in
            store().set_meta("claude:last_error", json.dumps({"at": time.time(), "error": str(e)[:200], "fp": _key_fp()}))
            note = (f" Right now {MASTER_MODEL} couldn't answer ({str(e)[:120]}), so you're running on the "
                    f"stand-in model, {TIER_LLM['low_brain'][1]}. If asked which model you are, say that.")
            messages = ([dict(messages[0], content=messages[0]["content"] + note)] + messages[1:]
                        if messages and messages[0]["role"] == "system" and isinstance(messages[0]["content"], str)
                        else messages)
    t = "low_brain" if tier == "master" else tier
    if t == "manager" and desk_on():  # Groq's free tier can't take the managers' prompts (8k tokens a minute)
        try:
            text = claude_chat(messages, max_tokens, model=DESK_MODEL, effort=DESK_EFFORT)
            _note_model_selection("manager", "anthropic", DESK_MODEL, "desk")
            return text
        except LLMError:
            pass  # Groq, then Gemini, as before
    need = est_tokens(messages) + max_tokens
    if primary is None and os.environ.get(ROUTE_CONFIG_VARS[t][0], "").strip():
        primary = _route_primary(t)  # an explicit ROUTE_<TIER>_* pair reaches every call of this tier
    if fallback is None and os.environ.get(ROUTE_FALLBACK_VARS[t], "").strip():
        fallback = _route_fallback(t) or "off"
    provider, model = primary if primary is not None else TIER_LLM[t]
    tried = {(provider, model)} | ({("anthropic", DESK_MODEL)} if t == "manager" and desk_on() else set())
    fits, why = room_for(provider, model, need)
    if not fits:  # don't send what it would refuse: straight to the next model
        first = LLMError(f"{provider} {model}: {why}", retryable=True, timed_out=True)
    else:
        try:
            text = _llm_call(provider, model, messages, max_tokens)
            _note_model_selection(t, provider, model, "primary")
            return text
        except LLMError as e:
            if not e.retryable:
                raise
            first = e
        if not first.timed_out:
            time.sleep(LLM_RETRY_DELAY)
            try:
                text = _llm_call(provider, model, messages, max_tokens)
                _note_model_selection(t, provider, model, "retry", _model_error_category(first))
                return text
            except LLMError as e:
                if not e.retryable:
                    raise
    if fallback is None:
        fb_provider, fb_model = FALLBACK_LLM.get(t, (None, "off"))
    elif fallback == "off":
        fb_provider, fb_model = None, "off"
    else:
        fb_provider, fb_model = fallback
    err = first
    if fb_model != "off" and os.environ.get(PROVIDERS[fb_provider][1]):
        tried.add((fb_provider, fb_model))
        fits, why = room_for(fb_provider, fb_model, need)
        try:
            if not fits:
                raise LLMError(f"{fb_provider} {fb_model}: {why}")
            text = _llm_call(fb_provider, fb_model, messages, max_tokens)
        except LLMError as e:
            err = LLMError(f"{first} (and the fallback, {fb_model}, failed too: {e})")
        else:
            try:
                store().set_meta("llm:fallback", json.dumps({"tier": t, "at": time.time(), "why": str(first)[:160],
                                                             "model": fb_model}))
            except Exception:
                pass  # noting it must never cost the reply
            _note_model_selection(t, fb_provider, fb_model, "tier_fallback", _model_error_category(first))
            return text
    got = borrow_help(t, messages, max_tokens, need, tried, str(first))
    if got is not None:
        return got
    raise err
