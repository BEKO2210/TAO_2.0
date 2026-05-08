# Hygen scaffolding templates

Templates for generating new modules in this repo. Run from the repo root:

```bash
npm install            # one-time, installs hygen as a devDependency
npx hygen agent new    # interactive: creates src/agents/<name>_agent.py + test
npx hygen collector new
npx hygen scoring new
npx hygen test new
npx hygen doc new
```

Or use the npm script aliases: `npm run new:agent`, `npm run new:collector`, etc.

## Generators

| Generator   | Creates                                                                 |
|-------------|-------------------------------------------------------------------------|
| `agent`     | `src/agents/<name>_agent.py` + `tests/test_<name>_agent.py`             |
| `collector` | `src/collectors/<name>.py`                                              |
| `scoring`   | `src/scoring/<name>_score.py` + `tests/test_<name>_score.py`            |
| `test`      | `tests/test_<name>.py` (variants for agent / collector / scoring)       |
| `doc`       | `docs/<name>.md`                                                        |

All generated agents follow the agent interface contract from `SPEC.md`:
`run`, `get_status`, `validate_input`, `AGENT_NAME`, `AGENT_VERSION`.

## Conventions

- Module names: `snake_case`. Class names: `PascalCase`.
- Helpers (`h.snake`, `h.pascal`, `h.upper`) are defined in `.hygen.js` at the repo root.
- Add new generators by creating `_templates/<generator>/<action>/*.ejs.t` files.
