# Website

The source for the skill index website, published to GitHub Pages by [.github/workflows/pages.yml](../.github/workflows/pages.yml) whenever `main` changes.

- `index.template.html` and `skills.template.html` are the two pages. `scripts/build_skill_index.py` fills in `__DATA__` (skills, plugins, tool coverage, contributors) and `__LOGO__`. Edit the templates, never the built pages.
- `assets/bloomreach-logo-icon.svg` and `assets/bloomreach-logo-text.svg` are Bloomreach's logo files, as served on bloomreach.com. Use them as they are; Bloomreach's brand team owns the logo rules.

Build it locally with `python3 scripts/build_skill_index.py --site _site`, then open `_site/index.html`.
