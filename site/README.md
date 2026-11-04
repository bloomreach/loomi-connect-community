# Website

The source for the skill index website, published to GitHub Pages by [.github/workflows/pages.yml](../.github/workflows/pages.yml) whenever `main` changes.

- `index.template.html`, `quickstart.template.html`, `skills.template.html` and `tools.template.html` (the tool map) are the four pages. `scripts/build_skill_index.py` fills in `__DATA__` (skills, plugins, tool coverage, contributors) and `__LOGO__`. Edit the templates, never the built pages.
- `assets/bloomreach-logo-icon.svg` and `assets/bloomreach-logo-text.svg` are Bloomreach's logo files, as served on bloomreach.com. Use them as they are; Bloomreach's brand team owns the logo rules.

The build also puts a ready-to-upload zip of every skill in `downloads/`, for claude.ai and ChatGPT.

`assets/theme.js` is the light/dark toggle in every page header. Pages follow the system setting until the visitor picks one, which is kept in their browser.

Build it locally with `python3 scripts/build_skill_index.py --site _site`, then open `_site/index.html`.
