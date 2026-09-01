# Gap analysis: Walter's editorial pass vs. what we caught (SIGCSE Pramana)

*PRELIMINARY. Input for a later synthesis into the `/paper-writing` skill. Built from Walter's
single editorial commit (`6232191`, "Walter's comments") against our `939ced9`. Arpit will do a
close edit on Overleaf next; the final skill refinements wait until we see how he reconciled
Walter's edits. The point of this doc: categorize what a domain-expert human caught that our
process (us + Codex audits) missed, and WHY, so the skill stops missing this class.*

## The headline
Walter's edits were almost all the same five moves, applied dozens of times. None was a content or
structure problem; every one was **local precision** that our process smoothed over. Most damning:
**three of the five classes are rules we already had** (named-over-vague, calibrated hedging,
cost=time) — we applied them too narrowly and failed to sweep the whole paper for the class.

## The five gap classes (with Walter's edits as evidence)

### 1. Over-asserted empirical universals — the hedging gap (biggest, and a REPEAT)
We state empirical claims as universals; Walter adds calibrated hedges.
- "Checking an answer **means** running an experiment" → "**typically** means"
- "setting one up by hand **takes** days" → "**can take** days" (several times)
- "Producing it by hand **takes** days" → "**can take**"
- "By hand, a single scenario **means**…" → "**can take** days, simply because it…"

This is exactly Shenker **R17 (calibrated hedging on rationale)** — which is *in our profile* — and
Walter had *already* flagged one instance ("a why question is empirical" → "often empirical"). We
fixed that ONE spot and never generalized: every "takes days / means / is" universal needed the same
treatment. Codex even flagged one ("showed"→"suggested") but we treated it as a one-off.
**Why we missed it:** LLMs over-assert by default (fluent declaratives feel authoritative), and we
patch flagged instances instead of deriving the *class* and sweeping for it.

### 2. Vague pronouns/demonstratives — named-over-vague, applied too narrowly
We lean on "it / this / these / that <noun>"; Walter names the referent.
- "produce **it** for free" → "produce **the how**"
- "deriving **why**" → "deriving **the** why"; "produces **this how**" → "**performs these tasks
  (i.e., the how)**"
- "plots **these**" → "plots **this data**"
- "running **it**" → "running **that application**"; "**an** application's interface" → "**the**
  application's interface"
- "the cost of **that data**" → "the cost of **obtaining** that data"

We KNOW named-over-vague — but we scoped it to mechanisms/baselines/metrics, not to **pronouns and
demonstratives**. Every "it/this/these/that" is a place the referent can be named.
**Why we missed it:** the rule lived as "name your mechanisms," not "every pronoun has a nameable
antecedent." Fluent prose tolerates vague pronouns, so nothing felt wrong.

### 3. Thing-vs-process and abstract-vs-concrete conflation (cost=time is a REPEAT)
We conflate a thing with producing it, and abstract cost with concrete time; Walter disambiguates.
- "makes **the data** cheap" → "makes **generating** the data cheap" (twice)
- "evidence on **cost**" → "cost **(i.e., time saved)**"
- "would have been at least **twice as costly**" → "would have taken **at least twice as much time**"

The cost=time clarification is the SECOND repeat: Walter raised it earlier, we fixed the first uses
and the §4.3 opener, but did not propagate it to "twice as costly," "the data cheap," and "evidence
on cost." **Why we missed it:** we don't propagate a one-time clarification globally, and an LLM
doesn't *feel* the cost-vs-time or data-vs-generating-data conflation because both read fluently.

### 4. Folksy approximation vs explicit precision
We round to colloquial fractions; Walter wants explicit, venue-precise numbers and glosses.
- "for **a sixth** of them" → "for **about 20%** of them"
- "Python proficiency is **4 of 5**" → "**4 out of 5**"
- "application workloads, a video call or a streamed movie" → "**(e.g.,** a video call or a streamed
  movie**)**"

**Why we missed it:** we optimized for readable prose ("a sixth") over explicit precision, and we
under-use formal e.g./i.e. glosses that a precise academic register expects.

### 5. Vague actors and colloquial "you" — named-over-vague for subjects
- "**you** can tell which CCA" → "**a host** can tell"; "between **you and it**" → "between **the
  host and the server**"
- "how **a subset** designed experiments" → "a subset **of participants**"
- "**A second** expected" → "A second **student** expected"; "**Two** reported" → "**Two
  respondents** reported"

**Why we missed it:** same root as #2 — named-over-vague never reached *subjects/actors*, and we let
colloquial second-person "you" stand in a formal claim.

## The meta-causes (why our process didn't catch any of this)
1. **Rules scoped too narrowly.** Named-over-vague and calibrated hedging were in the profile but
   applied to mechanisms/rationale only, never extended to pronouns, actors, or class-wide sweeps.
2. **Point-fixes, not class-sweeps.** When Walter (or Codex) flagged ONE instance, we fixed that
   instance and moved on instead of deriving the rule and grepping the whole paper for siblings.
3. **No global propagation of a clarification.** cost=time was fixed in three places and missed in
   three others; there is no "adopt once → sweep everywhere" step.
4. **LLM-on-LLM review shares the blind spots.** Codex caught ~1 of these classes. Over-assertion,
   vague referents, and thing/process conflation are *collective LLM tendencies*, so an LLM reviewer
   doesn't flag them. A domain-expert human does. **Lesson: budget a human-expert precision pass;
   do not assume a Codex audit substitutes for it.**
5. **Fluency bias.** Our edits optimize for smooth, confident prose. Every one of Walter's changes
   trades a hair of smoothness for precision — the exact tradeoff an LLM under-weights.

## Candidate skill additions (to finalize after Arpit's Overleaf pass)
- **A "precision sweep" gate** with four scans, each run paper-wide (not per-edit):
  (a) **Hedge scan:** flag every empirical/causal universal ("X takes/means/is Y"); ask "always, or
  can/typically/often?" (R17).
  (b) **Referent scan:** flag every "it/this/these/that <noun>" and every vague subject
  ("a subset / some / you / a second / two"); name the antecedent/actor.
  (c) **Conflation scan:** flag thing-vs-process (data vs generating data) and abstract-vs-concrete
  (cost vs time); disambiguate.
  (d) **Explicitness scan:** prefer explicit numbers and e.g./i.e. glosses over folksy fractions,
  calibrated to the venue.
- **"Adopt once → sweep everywhere":** when any clarification is accepted (e.g., cost=time), grep the
  whole paper for the concept and apply it at every occurrence before moving on.
- **"Generalize a flag into a class":** when a reviewer/Codex flags one instance, treat it as a
  representative of a class and sweep for siblings, rather than a point-fix.
- **Process note:** an LLM reviewer (Codex) does NOT substitute for a domain-expert human pass on
  precision; the over-assertion / vague-referent / conflation classes are exactly what LLM-on-LLM
  review is blind to. Plan a human-expert read for these.

## One divergence to reconcile in the synthesis
Walter ADDED an em-dash ("success report\textbf{---}the reasoning"). The no-em-dash rule is Arpit's
standing style, not a shared lab rule; a co-author edit reintroduced one. The synthesis should note
that author-specific style rules (no em-dash) need re-application after any co-author pass — they are
not self-enforcing across collaborators.
