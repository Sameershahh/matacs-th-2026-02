# MATACS-TH-2026-02: AI proposal triage design

- **Name:** Sameer Shah
- **Reference:** MATACS-TH-2026-02
- **Time spent:** 40 min

## How I used AI tools

I used Perplexity and ChatGPT to research the topic and understand the brief, and Claude to turn my own solution notes into the detailed design and the final repository files. I then used the OpenCode CLI agent to audit the repository against the brief's file names, structure, word limit and rules. Claude's first draft of the write-up ran to 1,091 words, over the 1,000-word limit, and its scoring code rounded one score to 76.2 instead of 76.3; both were caught during review and corrected before the final version.

## Files

- [WRITEUP.md](WRITEUP.md): answers to the five questions.
- [diagram/process-flow.png](diagram/process-flow.png): flow from upload to ranked output, showing AI steps, rule steps and human checkpoints.
- [PROMPTS.md](PROMPTS.md): the extraction prompt exactly as it is sent.
- [ranking.json](ranking.json): expected ranking of proposals A to E.
- [prototype/](prototype/): optional script that runs the prompt and scores the result.
  - [prototype/run.py](prototype/run.py)
  - [prototype/extract.py](prototype/extract.py)
  - [prototype/scoring.py](prototype/scoring.py)
  - [prototype/config.py](prototype/config.py)
  - [prototype/criteria/commercial_solar.json](prototype/criteria/commercial_solar.json)
  - [prototype/prompts/extraction_system.txt](prototype/prompts/extraction_system.txt)
  - [prototype/prompts/extraction_user.txt](prototype/prompts/extraction_user.txt)
  - [prototype/tests/test_scoring.py](prototype/tests/test_scoring.py)
  - [prototype/tests/test_extract.py](prototype/tests/test_extract.py)
  - [prototype/tests/__init__.py](prototype/tests/__init__.py)
  - [prototype/requirements.txt](prototype/requirements.txt)
  - [prototype/.env.example](prototype/.env.example)
  - [.gitignore](.gitignore)

## Prototype

The model reads each proposal and returns facts. Everything else is plain Python.

| File | Purpose |
|---|---|
| `prototype/criteria/commercial_solar.json` | Criteria, weights, limits and fact definitions for the category. |
| `prototype/prompts/` | The two prompt files used by the script, identical to PROMPTS.md. |
| `prototype/extract.py` | Builds prompts, calls the model, validates the reply, verifies quotes, screens for directed text. |
| `prototype/scoring.py` | Eligibility, limits, weighted scoring, ranking and reason text. No model calls. |
| `prototype/run.py` | Command line entry point. Writes each run to `prototype/runs/`. |
| `prototype/tests/` | Unit tests for scoring, config and extraction handling. |

Proposal text is not committed to this repository. To run the extraction, put one plain-text file per proposal in `prototype/samples/` named by letter (`A.txt`, `B.txt`, ...). That folder is git-ignored.

```
cd prototype
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key
python run.py --criteria criteria/commercial_solar.json --proposals samples --dry-run
python run.py --criteria criteria/commercial_solar.json --proposals samples
python run.py --criteria criteria/commercial_solar.json --extractions runs/<run>/extractions
python -m unittest discover -s tests
```

`--dry-run` prints the inputs, prompt hash and criteria hash and writes nothing. `--extractions` re-scores saved facts without calling the model. A run never overwrites an existing run folder.
