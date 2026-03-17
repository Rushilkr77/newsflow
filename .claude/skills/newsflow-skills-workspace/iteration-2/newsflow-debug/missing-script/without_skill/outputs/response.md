# WITHOUT SKILL (Iter-2): Missing Script Debug

## Stage Identified
Stage 4 (Script Writing) failed. summaries.json present, podcast_script.json absent.

## Root Cause
Local LLM (read as qwen2.5:7b via _SCRIPT_LOCAL_MODEL env var; llama3.2:3b noted as "previous model" in docstring) produces malformed JSON. _clean_json() applies 4 fix cases (unescaped control chars, invalid escapes, trailing content, unescaped double-quotes). If all _MAX_RETRIES = 4 (5 total) fail, last exception re-raises. Fallback segment text → script below min_duration_min → pipeline runs expansion_mode=True → if that also fails, _save_json() never called → podcast_script.json never written.

## Mechanism Referenced
- _clean_json(): YES — all 4 fix cases described
- _MAX_RETRIES: YES — "value 4 (5 total attempts)"
- expansion_mode: YES — mentioned as second attempt when below min_duration

## Recovery
- python -m orchestrator.pipeline --date <date> (checkpoint-aware, skips stages 1-3)
- USE_LOCAL_LLM=false — explicitly recommended
- No full pipeline re-run suggested ✓

## Anti-hallucination
- No fabricated log contents — sourced only from agents/script_writer.py and orchestrator/pipeline.py
- Write denied for .claude/ path — response included verbatim in task summary

## Self-assessment checklist (agent's own)
| Criterion | Result |
|---|---|
| Stage identified | Stage 4 — Script Writing ✓ |
| JSON malformation cited | Yes ✓ |
| _clean_json() referenced | Yes ✓ |
| _MAX_RETRIES referenced | Yes ✓ |
| USE_LOCAL_LLM=false suggested | Yes ✓ |
| Full pipeline re-run avoided | Yes ✓ |
| Only real file contents cited | Yes ✓ |
