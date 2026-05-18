# Release Skill
1. Check latest published version: `gh release list -L 5`
2. Confirm target remote with user (origin vs beta)
3. Run full test suite locally - DO NOT proceed if any fail
4. Bump version in manifest.json / pyproject.toml
5. Update CHANGELOG.md
6. Commit, tag, push to CONFIRMED remote
7. Verify release appears on GitHub
