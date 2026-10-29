# Write-up

**Assumptions.** The brief is from 2026, so "last 5 years" means 2021 onward. A bid over the budget ceiling or over 16 weeks is excluded. A bid that is silent on a mandatory item is held for a person, not failed, because silence can also mean the extraction missed it. A bid that says the electrical work goes to a subcontractor, to be confirmed later, does not hold the licence and fails.

## 1. AI vs. rules

AI does one job. It reads a proposal and turns the prose into a fixed list of facts (price, weeks, warranty years, whether the bidder holds the licence, and so on), each with an exact quote. Everything after that is plain code: mandatory checks, budget and schedule limits, scoring formulas, weights, sorting and the reason text.

The line sits where reading turns into deciding. Reading free text is hard for rules, since "licence held" can be phrased many ways, and one sample says the opposite in a friendly sentence. Deciding is hard for AI to repeat. Pass/fail, a weighted sum and a sort must give the same answer every time, be explainable line by line, and change when an admin changes a weight, not when someone edits a prompt. The reasons are also built from facts and flags rather than written by the AI, so they cannot claim anything the data does not support.

The prompt takes its fact list from the criteria config, so changing weights, thresholds or which facts feed a criterion needs no code change. A new kind of scoring formula still needs a developer.

## 2. Consistency and explainability

The AI's role is small. Temperature is 0, the output follows a fixed JSON schema, and every run records the prompt hash and criteria version. Scoring is deterministic code, so the same stored facts always give the same ranking, and ties break by proposal letter so input order never matters. The prototype tests check this.

A fresh model call on the same PDFs could still extract slightly differently, since output is not guaranteed identical even at temperature 0. So facts are stored, and a re-run reuses them unless the reviewer asks for re-extraction, in which case differences are shown.

For each proposal the reviewer sees the score per criterion, the points lost, the flags, and the quote behind every number. The code checks that each quote appears in the source text, and downgrades the fact to "ambiguous" if it does not. Price and timeline are scored relative to the best eligible bid, so they shift if the set of bids changes. That keeps them easy to explain ("3% above the cheapest"), and the screen states the baseline.

## 3. Human in the loop

- **Before the ranking is trusted:** the reviewer works through the flagged and ineligible lists, opens quotes, and can correct a fact. A correction is stored beside the original extraction, never over it.
- **After ranking:** the reviewer can move or exclude a proposal, with a written reason required.
- **The award:** a person decides, outside the tool. The tool never awards anything.

The audit log is append-only. Per run it holds who ran it, when, the model and settings, prompt hash, criteria version, source file hashes, extracted facts with quotes, flags, scores and the final ranking, plus every correction or override with user and reason.

## 4. Changing criteria

Criteria are versioned. An edit creates version N+1 and never alters N. Every result stores the version it used, so old rankings stay explainable, and earlier results are marked stale after an edit.

Re-scoring recomputes from the stored facts, so a weight or threshold change needs no AI call. If the edit adds a new fact, only that fact is extracted, and only for proposals that lack it. Reviewer corrections carry over where the fact is unchanged. Both rankings are kept and the screen shows what moved. Before saving, the admin previews the effect on current results, and weights that do not total 100 are rejected. A prototype test reorders proposals under new weights with no new extraction.

## 5. Risks

- **Wrong extraction.** Schema and type validation, a retry with the rejection reason, and a required quote that must exist in the source. An unconfirmed mandatory item goes to a person and is never guessed.
- **Made-up facts.** "not_stated" is an allowed answer, the prompt forbids inference, and the AI never does arithmetic or scoring. An invented quote fails the source check.
- **Manipulation.** One sample (C) contains a line telling automated reviewers to rank it first. Proposal text is passed as quoted data, and the system prompt says never to follow instructions inside it. The model reports such lines, and a separate rule screen catches them if it does not. Any hit holds the proposal for a person. The line cannot change a score, because scoring is code that reads only facts. I flag C and show its provisional score so the reviewer can decide.
- **Bias.** The model sees only the proposal, and scoring ignores company name, size and location. Names can be masked in the reviewer view. Team and approach come from yes/no checklist facts, so polished writing earns nothing extra.
- **Unverifiable claims.** Licence numbers, WSIB and insurance are extracted for a person, or a registry check, to verify before any award. "Named lead" means the proposal says the lead is named. Checking the name is human work.
- **Cost and reliability.** One call per proposal, results cached by file hash, no calls when re-scoring. A failed extraction flags that proposal without stopping the batch. Very long PDFs would need chunking, which the prototype lacks.
- **Confidentiality.** Proposals hold business information, so use no-training provider terms, limited access and a retention period.

## Sample set

A first, E second. B is ineligible, C and D are held. Details are in ranking.json.
