# Contributing to PhotoScribe

PRs are welcome. Here's how to keep things smooth.

## Getting started

1. Fork the repo
2. Clone your fork and set up the dev environment:
   ```bash
   git clone https://github.com/YOUR_USERNAME/PhotoScribe.git
   cd PhotoScribe
   python3.13 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Create a branch for your work: `git checkout -b your-feature-name`

## Guidelines

- **Keep PRs focused.** One feature or fix per PR. Easier to review, easier to merge.
- **Don't break existing functionality.** If you're adding a headless mode, the GUI should still work exactly as before.
- **Test your changes.** If you're adding tests (please do), put them in a `tests/` directory.
- **Match the existing style.** No linters enforced yet, but keep it consistent with what's there.
- **No new cloud dependencies.** PhotoScribe is local-first by design. Everything runs on the user's machine.
- **Python 3.10-3.13 compatibility.** Don't use 3.14+ features.

## What we'd love help with

- Headless/CLI mode for scripting and pipeline integration
- Tests (there are currently none, so anything is an improvement)
- Better error handling and edge cases
- DAM integration (digiKam, darktable, etc.)
- Performance improvements for large batches
- Documentation

## What to avoid

- Adding cloud-based AI services or API calls to external servers
- Changing the metadata writing approach without discussion (IPTC/XMP via ExifTool is deliberate)
- Major UI overhauls without opening an issue first to discuss

## Submitting a PR

1. Push your branch to your fork
2. Open a PR against `main`
3. Describe what it does and why
4. If it's a bigger feature, open an issue first so we can discuss the approach before you build it

## Questions?

Open an issue or start a discussion. No stupid questions.
