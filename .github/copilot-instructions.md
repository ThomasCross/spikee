# Spikee AI Agent Instructions

Spikee is a modular LLM security testing toolkit (v0.6.1) for prompt injection/jailbreak assessment.

## Core Architecture

**Two-Stage Pipeline**: `generator.py` → `tester.py` → `results.py`
- Generator composes JSONL datasets from seed folders, applying plugin transformations
- Tester executes entries via `AdvancedTargetWrapper` (handles retries, throttling, multi-turn)
- Results analyzer parses JSONL into HTML reports with breakdowns by jailbreak/instruction/plugin

**Module Loading System** (`utilities/modules.py`):
```python
# Resolution order: workspace/{type}/ → spikee/{type}/ → spikee/data/
load_module_from_path(name, module_type):  # Returns class instance OR legacy module
  1. Try os.path.join(cwd, module_type, f"{name}.py")
  2. Fall back to importlib.import_module(f"spikee.{module_type}.{name}")
  3. Call _resolve_impl_class() to find concrete subclass via inspect.getmembers()
  4. Return _instantiate_impl() OR raw module for legacy compatibility
```

**OOP Migration Pattern** (v0.5.0 → v1.0.0 deprecation):
- All new modules inherit from `spikee/templates/{target,plugin,attack,judge}.py` ABC classes
- Legacy function-based modules (`def process_input()` at module level) still load but deprecated
- Code uses `inspect.signature()` to detect parameter support (e.g., `"plugin_option" in params`)
- Use `hasattr(module, "transform")` to check for methods before calling

## Module Base Class Pattern

**CRITICAL**: All templates inherit from `Module` ABC (`templates/module.py`). Every module MUST implement:

```python
from spikee.templates.module import Module
from typing import Tuple, List

class MyModule(Module):
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        # MUST return Tuple[List[ModuleTag], str] - used by 'spikee list'
        return [ModuleTag.SINGLE], "Brief description of what this module does"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        # CRITICAL RETURN TYPE: Tuple[List[str], bool]
        # Missing type hints break isinstance() checks in get_default_option()
        # First item in options_list is the DEFAULT used when no option specified
        # Bool indicates if module needs LLM provider to operate (affects error messages)
        return ["mode=aggressive", "mode=stealth"], False  # No LLM needed
        # OR
        return ["model=gpt-4o", "model=claude-3.5"], True   # Requires LLM
```

**Type Hint Requirements**:
- `get_default_option()` checks `isinstance(available, tuple)` - returns `None` if not tuple
- CLI validates LLM requirement flag before running - prevents cryptic API key errors
- `spikee list` uses return types to format output tables correctly
- **Always import typing types** - runtime type checks depend on proper annotations

## Template Contracts

### Target (`spikee/templates/target.py`)
```python
from typing import Optional, Dict, Tuple, List

class MyTarget(Target):
    def __init__(self):
        super().__init__()
        # Configure turn support - tester.py checks this via target_module.config
        self.config: Dict[str, bool] = {
            "single-turn": True,   # Accepts string input
            "multi-turn": True,    # Accepts list[str] for conversation
            "backtrack": False     # Supports removing last turn
        }
    
    def process_input(self, input_text: str, system_message: Optional[str] = None, 
                     target_options: Optional[str] = None) -> str | bool:
        # CRITICAL TYPE: Return str for LLM outputs, bool for guardrails (True = bypassed)
        # AdvancedTargetWrapper relies on isinstance(response, bool) to detect guardrail mode
        # Raise GuardrailTrigger(msg, categories={}) for blocked payloads
        # Raise RetryableError(msg, retry_period=60) for 429/throttling
        pass
    
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        return [ModuleTag.SINGLE, ModuleTag.MULTI], "My custom target implementation"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        # First option is default, bool=True means needs LLM provider
        return ["temperature=0.7", "temperature=0.0"], True
```

### Plugin (`spikee/templates/plugin.py` or `basic_plugin.py`)
```python
from typing import Optional, List, Tuple

class MyPlugin(BasicPlugin):  # BasicPlugin auto-handles exclude_patterns via regex split
    def plugin_transform(self, text: str, plugin_option: Optional[str] = None) -> str:
        # Transform only non-excluded chunks
        return text.upper()
    
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        return [ModuleTag.SINGLE], "Uppercase transformation plugin"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        return ["variants=50", "variants=100"], False  # No LLM needed
        
# OR for full control:
class MyPlugin(Plugin):
    def transform(self, text: str, exclude_patterns: Optional[List[str]] = None) -> str | List[str]:
        # CRITICAL TYPE: Return str | List[str] for variant detection
        # Generator checks isinstance(result, list) to determine multi-variant behavior
        # Return str for single variant, List[str] for N variants
        return [text.upper(), text.lower()]
    
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        return [ModuleTag.SINGLE], "Case variation plugin"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        return ["mode=both", "mode=upper", "mode=lower"], False
```

### Attack (`spikee/templates/attack.py`)
```python
from typing import Optional, Tuple, Dict, Any, Callable, List

class MyAttack(Attack):
    def __init__(self):
        super().__init__(turn_type=Turn.SINGLE)  # or Turn.MULTI
    
    def attack(self, entry: Dict[str, Any], target_module, call_judge: Callable,
               max_iterations: int, attempts_bar=None, bar_lock=None) -> Tuple[int, bool, str, str]:
        # CRITICAL RETURN TYPE: Tuple[attempts: int, success: bool, modified_input: str, response: str]
        # Tester.py unpacks this tuple - wrong size or element types cause immediate crashes
        # CRITICAL: Update progress bar with bar_lock for each attempt
        # target_module is AdvancedTargetWrapper - handles retries automatically
        for i in range(max_iterations):
            with bar_lock:
                attempts_bar.update(1)
            modified = modify_payload(entry["payload"])
            response, _ = target_module.process_input(modified, entry.get("system_message"))
            if call_judge(entry, response):
                return (i+1, True, modified, response)
        return (max_iterations, False, modified, response)
    
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        return [ModuleTag.SINGLE], "Iterative payload mutation attack"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        # LLM-based attacks need bool=True to validate provider availability
        return ["model=gpt-4o", "model=claude-3.5"], True
```

### Judge (`spikee/templates/judge.py`)
```python
from typing import Optional, Union, List, Tuple

class MyJudge(Judge):
    def judge(self, llm_input: str, llm_output: str, judge_args: Union[str, List[str]], 
             judge_options: Optional[str] = None) -> bool:
        # CRITICAL RETURN TYPE: bool (True = attack succeeded, False = failed)
        # Tester.py uses this directly in success/failure counting
        # judge_args comes from dataset entry, judge_options from CLI --judge-options
        return judge_args in llm_output
    
    def get_description(self) -> Tuple[List[ModuleTag], str]:
        return [ModuleTag.SINGLE], "Substring match judge"
    
    def get_available_option_values(self) -> Tuple[List[str], bool]:
        # Basic judges: bool=False, LLM judges: bool=True
        return ["case_sensitive=true", "case_sensitive=false"], False
```

## Exception-Based Control Flow

**Custom Exceptions** (`tester.py`):
```python
GuardrailTrigger(message, categories={})  # Raised by targets when blocked - triggers retry
RetryableError(message, retry_period=60)   # 429/throttling - triggers exponential backoff
MultiTurnSkip(message)                     # Single-turn target got multi-turn input - skip entry
```

**AdvancedTargetWrapper Pattern** (wraps `process_input()` with retry logic):
- Introspects target signature via `inspect.signature()` to detect optional params and type hints
- Only passes kwargs target actually supports (`target_options`, `logprobs`, `spikee_session_id`, etc.)
- **Type hints on optional parameters help introspection** - wrapper checks `param.annotation` to determine types
- Catches exceptions above and retries up to `max_retries`, respecting `throttle` delays
- Returns `(response: str, meta: Any)` tuple or unwraps to `response` alone - type depends on target

## Data Flow Internals

**Generator Pipeline** (`generator.py`):
1. `Entry()` class builds dataset entries with `EntryType` enum (DOCUMENT, SUMMARY, QA, ATTACK)
2. `insert_jailbreak()` injects payloads at start/middle/end or via `<PLACEHOLDER>` substitution
3. `apply_plugin()` checks signature for `plugin_option` param, handles piping via `~` separator
4. Plugins returning `List[str]` create N dataset variants per base entry
5. `Entry.to_entry()` serializes to JSONL dict with `long_id` for traceability

**Tester Workflow** (`tester.py`):
```python
process_entry(entry, target_module, ...):
  1. _do_single_request() - standard attempts (up to --attempts)
  2. If all fail AND attack_module exists:
     - Call attack_module.attack() with wrapped target
     - Attack updates attempts_bar with bar_lock per iteration
     - Returns first success OR final failure
  3. Append result dicts to output_file via append_jsonl_entry()
```

**Multi-Turn Support** (`StandardisedConversation` in `templates/`):
- Tree structure: `{msg_id: {"parent": int, "children": [], "data": Any, "attempt": bool}}`
- Root always node 0, tracks conversation branches for backtracking attacks
- Serialized to JSON string in result dict `"conversation"` field

## Signature Introspection Patterns

**Backward Compatibility Check** (appears throughout codebase):
```python
sig = inspect.signature(module.transform)  # or .attack, .judge, .process_input
params = sig.parameters

# Check parameter existence (type hints optional but recommended)
if "plugin_option" in params:
    result = module.transform(text, exclude_patterns, plugin_option)
else:
    result = module.transform(text, exclude_patterns)  # Legacy module

# Type hint checking for advanced behavior
if "plugin_option" in params:
    param = params["plugin_option"]
    # param.annotation available if type hints present: Optional[str], str | None, etc.
    if param.default is inspect.Parameter.empty:
        # Required parameter - always pass
        pass
```

**Module Instance vs Legacy Module**:
- `_resolve_impl_class()` uses `inspect.getmembers()` to find concrete subclass
- If found: instantiate and return class instance
- If not found: return raw module for legacy function-based hooks
- `get_options_from_module()` tries `module.get_available_option_values()` first, then instantiates if `inspect.ismodule()`
- **Type checking pattern**: `isinstance(available, tuple)` used to detect proper return types
- Methods without type hints still work but may fail `isinstance()` checks in some code paths

## Critical Implementation Details

**Plugin `exclude_patterns` Handling**:
- `BasicPlugin` base class auto-implements via `re.split(compound_regex, text)`
- Chunks matching `exclude_patterns` preserved verbatim, others transformed
- Pattern: `compound = "(" + "|".join(exclude_patterns) + ")"` then `re.fullmatch(chunk)`

**Progress Bar Management**:
- All modifications require `with bar_lock: attempts_bar.update(1)`
- On early success, adjust `attempts_bar.total` to skip remaining iterations:
  ```python
  attempts_bar.total = attempts_bar.total - (planned_iterations - actual_iterations)
  ```

**Dataset Entry Long IDs**:
- Format: `{task_type}_{doc_id}_{jailbreak_id}_{instruction_id}_{position}{plugin_suffix}`
- Suffixes: `-p{prefix_id}`, `-s{suffix_id}`, `-sys` (system message), `{attack_name}` (dynamic)
- Used for result grouping and resume file matching

**Resume Logic** (`tester.py` regions):
- `_find_resume_candidates()` uses `build_resource_name()` for exact tag matching
- Interactive prompt via `InquirerPy` if TTY detected
- `--auto-resume` silently picks latest, `--no-auto-resume` forces fresh

## Testing Patterns

**Functional Tests** (`tests/functional/`):
- Use `tmp_path` fixture + `subprocess.run(["spikee", "generate", ...])` 
- Helpers in `utils.py`: `_split_base_and_plugin_entries()`, `_load_plugin_module()`
- Tests verify JSONL structure, plugin transformations, resume merging

**Inference Tests** (`tests/inference/`):
- Parameterized via `@pytest.mark.parametrize` over target/attack/judge combinations
- Require API keys in `.env` - skip if missing

## Type Hinting Philosophy

**Critical Type Hints** (breaks functionality if missing):
1. **Module methods**: `get_description() -> Tuple[List[ModuleTag], str]` and `get_available_option_values() -> Tuple[List[str], bool]`
   - `get_default_option()` checks `isinstance(available, tuple)` - returns `None` on type mismatch
   - Missing tuple type breaks default option resolution and CLI startup

2. **Attack return types**: `attack(...) -> Tuple[int, bool, str, str]`
   - Tester unpacks: `attempts, success, modified, response = attack_module.attack(...)`
   - Wrong tuple size or element types cause immediate crashes

3. **Plugin return variance**: `transform(...) -> str | List[str]`
   - Generator checks `isinstance(result, list)` to detect multi-variant behavior
   - Missing union type leads to incorrect dataset generation

4. **Target return discrimination**: `process_input(...) -> str | bool`
   - `bool` return detected via `isinstance(response, bool)` for guardrail mode
   - Type confusion breaks success detection

**Recommended Type Hints** (improves introspection):
- Optional parameters: Use `Optional[str]` or `str | None` for signature introspection
- Callables: Type `call_judge: Callable` for better IDE support and documentation
- Dicts: Specify `Dict[str, Any]` for `entry` parameters to clarify structure
- Config dicts: Type `self.config: Dict[str, bool]` to document expected keys

**Import Pattern**:
```python
from typing import Tuple, List, Optional, Dict, Any, Callable, Union
# Use Union[str, List[str]] for Python <3.10, or str | List[str] for 3.10+
```

## Common Code Patterns

**Options String Parsing**:
```python
# Input: "plugin1:key=val,key2=val2;plugin2:key=val"
parse_plugin_options(str) -> Dict[str, str]  # Returns dict[plugin_name, option_string]
parse_options(str) -> Dict[str, str]         # Single module's options as dict[key, value]
```

**JSON Extraction from LLM** (`utilities/modules.py`):
- `extract_json_or_fail()` - strips markdown fences, fixes unescaped quotes, balanced-bracket scan
- Used by LLM-based plugins/attacks that expect structured output

**Guardrail Testing**:
- Target returns `bool`: True = bypassed (success), False = blocked (failure)
- OR raises `GuardrailTrigger` with optional `categories` dict for categorization

## Development Workflow

```bash
pip install -e .                 # Editable install - no reinstall needed
pytest tests/functional -v       # Run integration tests (no API keys)
pytest tests/inference -v        # Run LLM tests (requires .env)
spikee list {targets|plugins}    # Discover available modules
```

## Commit Prefixes

`feat:`, `fix:`, `change:`, `dataset:`, `dev:`, `docs:` - only first 4 in CHANGELOG.md
