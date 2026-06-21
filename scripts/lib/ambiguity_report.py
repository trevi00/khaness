"""ambiguity_report — read-only per-component surface for the interview ambiguity gate.

Closes the harness-interview gap: "scoring opaque to user; only aggregate and pass/fail
returned; no per-component delta shown" — the user can't tell WHICH axis (6W coverage
vs lexical entropy vs uncertainty markers) is driving the ambiguity, so they don't know
what to clarify next.

This is PURE READ over lib.ambiguity_score.AmbiguityScore — it adds NO scoring semantics
(the aggregate/weights/threshold record-semantics of ambiguity_score are gated at
enable-skill tier per that module's docstring; a formatter that only reads the frozen
result is not a semantics change). It surfaces the WEIGHTED CONTRIBUTION of each axis
(so the dominant driver is obvious) and round-to-round deltas.
"""
from __future__ import annotations

# weights order in AmbiguityScore.weights == (coverage_gap, lexical_entropy, unknown_marker_density)
_AXES = ("coverage_gap", "lexical_entropy", "unknown_marker_density")


def component_breakdown(score) -> dict:
    """Per-axis {value, weight, contribution} + the dominant (highest-contribution) axis.
    contribution = weight * value (its share of the aggregate). Pure read of a frozen
    AmbiguityScore (duck-typed: needs the 3 component attrs + .weights/.aggregate)."""
    w = tuple(score.weights)
    values = {
        "coverage_gap": float(score.coverage_gap),
        "lexical_entropy": float(score.lexical_entropy),
        "unknown_marker_density": float(score.unknown_marker_density),
    }
    weights = {"coverage_gap": float(w[0]), "lexical_entropy": float(w[1]),
               "unknown_marker_density": float(w[2])}
    axes = {
        ax: {"value": round(values[ax], 4), "weight": round(weights[ax], 4),
             "contribution": round(weights[ax] * values[ax], 4)}
        for ax in _AXES
    }
    dominant = max(_AXES, key=lambda ax: axes[ax]["contribution"])
    return {
        "aggregate": round(float(score.aggregate), 4),
        "threshold": round(float(score.threshold), 4),
        "passes_gate": bool(score.passes_gate),
        "axes": axes,
        "dominant_axis": dominant,
    }


def render_breakdown(score) -> str:
    b = component_breakdown(score)
    gate = "PASS" if b["passes_gate"] else "FAIL"
    lines = [f"[ambiguity] aggregate={b['aggregate']} (threshold={b['threshold']}, {gate}); "
             f"dominant driver: {b['dominant_axis']}"]
    for ax in _AXES:
        a = b["axes"][ax]
        mark = "  <- focus here" if ax == b["dominant_axis"] and not b["passes_gate"] else ""
        lines.append(f"  {ax}: value={a['value']} x weight={a['weight']} = {a['contribution']}{mark}")
    return "\n".join(lines)


def component_delta(prev, cur) -> dict:
    """Round-to-round per-axis delta (cur - prev; NEGATIVE = improved, ambiguity dropped)
    + aggregate delta + whether any axis REGRESSED (got more ambiguous)."""
    pb, cb = component_breakdown(prev), component_breakdown(cur)
    axes = {ax: round(cb["axes"][ax]["value"] - pb["axes"][ax]["value"], 4) for ax in _AXES}
    return {
        "aggregate_delta": round(cb["aggregate"] - pb["aggregate"], 4),
        "axes_delta": axes,
        "regressed_axes": [ax for ax, d in axes.items() if d > 0],
        "improved": cb["aggregate"] < pb["aggregate"],
    }


def render_round(prev, cur) -> str:
    d = component_delta(prev, cur)
    arrow = "improved" if d["improved"] else ("regressed" if d["aggregate_delta"] > 0 else "no change")
    out = [f"[ambiguity Δ] aggregate {d['aggregate_delta']:+} ({arrow})"]
    if d["regressed_axes"]:
        out.append(f"  ⚠ regressed: {', '.join(d['regressed_axes'])}")
    out.append("  " + render_breakdown(cur))
    return "\n".join(out)
