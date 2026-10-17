.PHONY: help install install-claude install-codex hooks develop test

help:
	@printf '%s\n' \
		'make install          Install skills (Claude + Codex) and git hooks' \
		'make install-claude   Symlink skill .md files to ~/.claude/commands/' \
		'make install-codex    Install equity-analyst Codex skill to ~/.codex/skills/' \
		'make hooks            Register .githooks/ as the git hooks directory' \
		'make develop          Create .venv, install edgar package, open activated shell'

install: install-claude install-codex hooks

install-claude:
	@mkdir -p "$$HOME/.claude/commands"
	@for f in *.md; do \
		ln -sf "$(PWD)/$$f" "$$HOME/.claude/commands/$$f"; \
		echo "  linked ~/.claude/commands/$$f"; \
	done
	@echo "Claude skills installed."

install-codex:
	@sh ./scripts/install-codex-skill.sh

hooks:
	@sh ./scripts/install-git-hooks.sh

develop:
	@uv venv .venv --allow-existing
	@uv pip install --python .venv/bin/python --cache-dir .uv-cache -e scripts/edgar
	@printf '%s\n' 'Launching a subshell with .venv activated. Exit that shell to return.'
	@SHELL="$${SHELL:-/bin/zsh}"; . .venv/bin/activate && exec "$$SHELL" -i

test:
	@uv venv .venv --allow-existing
	@uv pip install --python .venv/bin/python --cache-dir .uv-cache -e 'scripts/edgar[dev]'
	@.venv/bin/python -m pytest scripts/edgar/tests/ -v
