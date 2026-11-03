# Contributing

Thanks for helping. This guide explains how to get a contribution merged.

## What we accept

- **Skills**: the main thing this repo collects. See [docs/skill-authoring.md](docs/skill-authoring.md).
- **Subagents**: Claude Code agent definitions for a role, for example "CRM analyst". These are Claude-only today.
- **Scripts**: helpers that a skill uses. They live inside that skill's `scripts/` folder.
- **Docs**: guides, fixes and improvements.
- **Sample connectors**: small MCP servers in `connectors/` for testing skills on a public Bloomreach REST API. Read-only unless stated, standard library only, keys from the environment, with offline tests. See the [charter](CHARTER.md#secrets-and-keys).

Everything must be built on Bloomreach's publicly available interfaces (MCP, REST, documented product formats), as the [charter](CHARTER.md) sets out.

If you're not sure something fits, [open an issue](../../issues/new/choose) before you start.

## How to contribute

**All submissions come in by forking the repository, making your changes in your fork, and opening a pull request.** This applies to everyone, including Bloomreach staff. Contributors don't get write access to this repository, and we can't accept changes sent any other way, such as by email, in an issue, or as a file attachment. Every change is reviewed in its pull request before it's merged.

**Every commit must be signed off** with `git commit -s`. It's one line, not a key or a form. See [Sign-off](#sign-off).

1. **Fork** the repository on GitHub (the **Fork** button), then clone your fork and create a branch:
   ```bash
   git clone https://github.com/<your-username>/loomi-connect-community.git
   cd loomi-connect-community
   git checkout -b skill/campaign-digest
   ```
2. **Copy the template.** Copy [templates/skill-template/](templates/skill-template/) to `plugins/<plugin>/skills/<skill-name>/`. Choose `loomi-engagement`, `loomi-discovery`, `loomi-platform` (skills that span products) or `loomi-product-data`. If your skill fits none of them, propose a new plugin in an issue first.
3. **Write the skill**, following [docs/skill-authoring.md](docs/skill-authoring.md).
4. **List it** in `plugins/<plugin>/README.md` with the right **Access**, and in [docs/start-here.md](docs/start-here.md).
5. **Validate it locally**, and run the unit tests:
   ```bash
   python3 scripts/validate_skills.py
   python3 -m unittest discover -s tests -t .
   claude plugin validate .        # if you have Claude Code installed
   ```
6. **Test it** against a real or sandbox Bloomreach project, in at least one Claude client and one OpenAI client if you can. Say which ones you used in the PR.
7. **Commit and push** to your fork, signing off every commit with `-s` (see [Sign-off](#sign-off)). Add `tests/` as well if you added or changed scripts:
   ```bash
   git add plugins/<plugin>/skills/<skill-name> plugins/<plugin>/README.md docs/start-here.md
   git commit -s -m "Add <skill-name> skill"
   git push origin skill/campaign-digest
   ```
8. **Open a pull request** from your fork's branch to `main` in `bloomreach/loomi-connect-community`, and fill in the template. GitHub offers a **Compare & pull request** button after you push. With the GitHub CLI you can run `gh pr create` instead.
9. **Respond to review.** Push further commits to the same branch, also signed off; the pull request updates automatically.

With the GitHub CLI, `gh repo fork bloomreach/loomi-connect-community --clone` does step 1's fork and clone in one go.

### Keeping your fork up to date

Before you start new work, sync your fork with the main repository:

```bash
git remote add upstream https://github.com/bloomreach/loomi-connect-community.git   # once
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

Or select **Sync fork** on your fork's GitHub page.

## Review

- Every PR from a contributor needs **one maintainer approval**.
- A maintainer's own PR can be merged once CI passes, without a second reviewer.
- A skill that **writes** data gets a closer review, whoever wrote it. That covers creating campaigns or scenarios, changing Discovery rules, starting experiments, and similar actions. Before merging, check that its Safety section lists every write, each write asks for an explicit yes first, and `agents/openai.yaml` sets `allow_implicit_invocation: false`.
- Reviewers check correctness, safety, clarity, and that the skill works across clients.
- CI runs `scripts/validate_skills.py` and the unit tests on every PR, and checks that every commit is signed off. All must pass.

Once a PR is merged, the contributor is credited in the skill's `metadata.author` and README.

## Hard rules

A PR that breaks any of these will not be merged:

- No credentials, tokens, API keys, real project or workspace IDs, customer data, or screenshots that show any of these. Use placeholders.
- Skills must not hard-code client-specific tool prefixes such as `mcp__loomi-connect-usa__...`. Refer to Loomi Connect tools by their plain names. See the authoring guide.
- Write operations must be labelled, and they must ask for confirmation before they run.
- Only Bloomreach's publicly available interfaces may be used: no internal or undocumented endpoints or tools, and no scraping the app. See the [charter](CHARTER.md#out-of-scope).

## Versioning

Bump `metadata.version` in the skill's frontmatter when you change a skill. Maintainers bump the plugin version in both manifests (`.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`) when they release.

## License

By contributing, you agree that your contribution is licensed under the [Apache 2.0 License](LICENSE).

## Sign-off

Every commit in a pull request must be signed off. CI checks this, and a pull request with a commit that isn't signed off can't be merged.

A sign-off isn't a cryptographic signature, and you don't need GPG or SSH keys. It's one line at the end of the commit message:

```
Signed-off-by: Your Name <you@example.com>
```

Adding it certifies the [Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change, or otherwise have the right to submit it under the Apache 2.0 License.

### How to sign off

1. **Set your name and email once.** Git uses them for both the commit author and the sign-off, and they must match:
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```
2. **Add `-s` when you commit:**
   ```bash
   git commit -s -m "Add campaign-digest skill"
   ```
   - **VS Code:** turn on the **Git: Always Sign Off** setting (`"git.alwaysSignOff": true`) and every commit you make from VS Code is signed off.
   - **GitHub's website:** commits you make there, such as edits and accepted review suggestions, are signed off for you.
   - **Other tools:** add the `Signed-off-by` line at the end of the commit message yourself.

### If you forgot

CI names each commit that's missing a sign-off. To fix them:

- **Just the last commit:**
  ```bash
  git commit --amend -s --no-edit
  git push --force-with-lease
  ```
- **Every commit on your branch:**
  ```bash
  git fetch upstream
  git rebase --signoff upstream/main
  git push --force-with-lease
  ```
  (If you haven't added `upstream`, see [Keeping your fork up to date](#keeping-your-fork-up-to-date).)

Your pull request updates automatically, and CI runs again.

## Code of conduct

This project follows our [Code of Conduct](CODE_OF_CONDUCT.md).
