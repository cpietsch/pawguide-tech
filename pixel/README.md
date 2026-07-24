# Pixel assets

These files can be exercised in AI Edge Gallery before the PawGuide Android host
is built:

- `system-prompt.txt` is the model policy;
- `model-evaluation.json` is the initial acceptance corpus.

Emergency STOP is intentionally absent from the corpus because it must never
enter the model path. Test it separately through the deterministic app router
described in `../docs/PIXEL_CLIENT.md`.
