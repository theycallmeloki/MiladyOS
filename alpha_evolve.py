#!/usr/bin/env python3
"""
MiladyOS AlphaEvolve - Evolutionary Pipeline Optimization

Integrates OpenEvolve with MiladyOS infrastructure for self-improving
Woodpecker CI pipelines. Uses local LLM infrastructure (Ollama/vLLM/LiteLLM)
for code generation and mutation.

Usage:
    python alpha_evolve.py evolve --template example-build --goal speed
    python alpha_evolve.py evolve --template docker-deploy --goal reliability
    python alpha_evolve.py status --evolution-id <id>
    python alpha_evolve.py list-evolved
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import click
import colorlog
import redis
import yaml

import evolve_fence

# Configure logging
logger = colorlog.getLogger("miladyos-alpha-evolve")
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))
logger.handlers = []
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class EvolutionGoal:
    """Defines an evolution optimization goal."""
    name: str
    description: str
    fitness_weights: Dict[str, float]
    prompt_hints: List[str]


@dataclass
class Candidate:
    """A candidate solution in the evolution."""
    id: str
    content: str
    generation: int
    fitness: Optional[float] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    parent_ids: List[str] = field(default_factory=list)
    island: int = 0
    feature_vector: List[float] = field(default_factory=list)


@dataclass
class EvolutionState:
    """Tracks the state of an evolution run."""
    evolution_id: str
    template_name: str
    goal: str
    generation: int = 0
    best_fitness: float = float('-inf')
    populations: List[List[Candidate]] = field(default_factory=list)
    archive: Dict[Tuple[int, ...], Candidate] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)


# ============================================================================
# Evolution Goals
# ============================================================================

EVOLUTION_GOALS = {
    "speed": EvolutionGoal(
        name="speed",
        description="Optimize for faster execution time",
        fitness_weights={
            "duration_score": 1.0,  # 0-1, higher = faster (normalized by evaluator)
            "success_rate": 0.3,
            "parallelism_score": 0.5,
        },
        prompt_hints=[
            "Add parallel execution where stages are independent",
            "Use shallow git clones (depth: 1)",
            "Implement caching for dependencies (npm, pip, etc.)",
            "Use faster alternatives (pnpm over npm, uv over pip)",
            "Minimize unnecessary file operations",
            "Use incremental builds where possible",
        ]
    ),
    "reliability": EvolutionGoal(
        name="reliability",
        description="Improve success rate and error handling",
        fitness_weights={
            "success_rate": 1.0,
            "error_handling_score": 0.5,
            "retry_coverage": 0.3,
            "timeout_coverage": 0.2,
        },
        prompt_hints=[
            "Add retry logic for flaky operations (network, docker)",
            "Implement comprehensive try-catch blocks",
            "Add timeouts to prevent hanging builds",
            "Validate inputs before processing",
            "Add health checks before deployments",
            "Implement graceful degradation",
        ]
    ),
    "resources": EvolutionGoal(
        name="resources",
        description="Optimize resource usage (CPU, memory, disk)",
        fitness_weights={
            "resource_efficiency": 1.0,
            "cleanup_score": 0.4,
            "constraint_score": 0.3,
        },
        prompt_hints=[
            "Add resource limits (memory, CPU) to containers",
            "Implement cleanup steps (docker prune, workspace cleanup)",
            "Use smaller base images",
            "Remove unnecessary dependencies",
            "Optimize artifact storage",
            "Use multi-stage builds to reduce final image size",
        ]
    ),
    "security": EvolutionGoal(
        name="security",
        description="Enhance security practices",
        fitness_weights={
            "security_score": 1.0,
            "secrets_handling": 0.5,
            "vulnerability_scan": 0.3,
        },
        prompt_hints=[
            "Never hardcode secrets, use credentials binding",
            "Add vulnerability scanning (trivy, snyk)",
            "Use specific image tags, not :latest",
            "Implement least-privilege principles",
            "Add SBOM generation",
            "Validate dependencies for known vulnerabilities",
        ]
    ),
    "observability": EvolutionGoal(
        name="observability",
        description="Improve logging, metrics, and tracing",
        fitness_weights={
            "logging_score": 0.4,
            "metrics_score": 0.3,
            "notification_score": 0.3,
        },
        prompt_hints=[
            "Add structured logging with context",
            "Emit build metrics (duration, size, test count)",
            "Implement notifications for failures",
            "Add build badges and status reporting",
            "Include performance timing for stages",
            "Generate build reports",
        ]
    ),
}


# ============================================================================
# LLM Integration
# ============================================================================

class LLMEnsemble:
    """Manages LLM calls for code generation and mutation."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.use_proxy = config.get("llm", {}).get("proxy", {}).get("enabled", False)
        self._setup_client()

    def _setup_client(self):
        """Setup LiteLLM client."""
        try:
            import litellm
            litellm.set_verbose = False

            if self.use_proxy:
                proxy_config = self.config["llm"]["proxy"]
                self.api_base = proxy_config.get("api_base", "http://localhost:4000/v1")
            else:
                primary = self.config["llm"]["primary"]
                self.api_base = primary.get("api_base", "http://localhost:11434/v1")

            self.litellm = litellm
            logger.info(f"LLM client configured with base: {self.api_base}")
        except ImportError:
            logger.warning("LiteLLM not available, using fallback generation")
            self.litellm = None

    async def generate_mutation(
        self,
        code: str,
        goal: EvolutionGoal,
        context: Dict[str, Any],
        temperature: float = 0.8
    ) -> str:
        """Generate a mutated version of the code."""
        prompt = self._build_mutation_prompt(code, goal, context)

        if self.litellm:
            return await self._call_llm(prompt, temperature)
        else:
            return self._fallback_mutation(code, goal)

    def _build_mutation_prompt(
        self,
        code: str,
        goal: EvolutionGoal,
        context: Dict[str, Any]
    ) -> str:
        """Build a context-rich prompt for mutation."""
        hints = "\n".join(f"- {hint}" for hint in goal.prompt_hints)

        history_context = ""
        if context.get("execution_history"):
            recent = context["execution_history"][-3:]
            history_context = "\n\nRecent execution results:\n"
            for i, exec_data in enumerate(recent):
                history_context += f"  Run {i+1}: {exec_data.get('result', 'unknown')} "
                history_context += f"in {exec_data.get('duration', '?')}s\n"

        error_context = ""
        if context.get("last_error"):
            error_context = f"\n\nLast error encountered:\n{context['last_error']}\n"

        return f"""You are an expert DevOps engineer optimizing Woodpecker CI pipelines.

GOAL: {goal.description}

OPTIMIZATION HINTS:
{hints}
{history_context}{error_context}
CURRENT PIPELINE CODE:
```yaml
{code}
```

REQUIREMENTS:
1. Output ONLY valid Woodpecker CI pipeline YAML
2. Preserve essential functionality while optimizing for: {goal.name}
3. Make meaningful improvements, not just cosmetic changes
4. Do not add unnecessary complexity
5. Ensure the pipeline remains runnable (valid YAML, steps with images)
6. ONLY change lines between an EVOLVE-BLOCK-START and EVOLVE-BLOCK-END
   marker. Keep both marker comment lines and every line OUTSIDE them
   byte-identical — the skeleton is immutable and edits to it are discarded.

Output the improved pipeline YAML only, no explanations:
```yaml
"""

    async def _call_llm(self, prompt: str, temperature: float) -> str:
        """Call LLM via LiteLLM."""
        try:
            primary = self.config["llm"]["primary"]
            model = primary.get("model", "ollama/deepseek-r1:14b")

            response = await asyncio.to_thread(
                self.litellm.completion,
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=primary.get("max_tokens", 4096),
                api_base=self.api_base,
            )

            content = response.choices[0].message.content

            # Extract code from markdown blocks if present
            if "```yaml" in content:
                match = re.search(r"```yaml\n(.*?)```", content, re.DOTALL)
                if match:
                    return match.group(1).strip()
            elif "```" in content:
                match = re.search(r"```\n?(.*?)```", content, re.DOTALL)
                if match:
                    return match.group(1).strip()

            return content.strip()

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._fallback_mutation(prompt, EVOLUTION_GOALS.get("speed"))

    def _fallback_mutation(self, code: str, goal: EvolutionGoal) -> str:
        """Rule-based fallback when LLM is unavailable (YAML-safe edits)."""
        import random

        mutations = {
            "speed": [
                ("npm install", "npm ci --prefer-offline"),
                ("pip install ", "pip install --no-cache-dir "),
            ],
            "reliability": [
                ("npm test", "npm test -- --reporter=dot"),
                ("sleep 10", "sleep 5"),
            ],
            "resources": [
                ("alpine:3.20", "alpine:3.20-slim"),
            ],
        }

        modified = code
        goal_mutations = mutations.get(goal.name, [])

        for old, new in goal_mutations:
            if random.random() < 0.4:
                modified = modified.replace(old, new, 1)

        return modified


# ============================================================================
# Pipeline Evaluators
# ============================================================================

class PipelineEvaluator:
    """Evaluates pipeline candidates through multiple stages."""

    def __init__(self, config: Dict[str, Any], runner=None):
        self.config = config
        self.runner = runner
        self.cache = {}

    async def evaluate(self, candidate: Candidate, goal: EvolutionGoal) -> Dict[str, float]:
        """Run cascade evaluation on a candidate."""
        metrics = {}

        # Stage 1: Syntax validation (fast)
        syntax_result = await self._check_syntax(candidate.content)
        metrics["syntax_valid"] = 1.0 if syntax_result["valid"] else 0.0
        if not syntax_result["valid"]:
            metrics["error"] = syntax_result.get("error", "Unknown syntax error")
            return metrics

        # Stage 2: Static analysis
        static_metrics = self._static_analysis(candidate.content, goal)
        metrics.update(static_metrics)

        # Stage 3: Dry run — local YAML structural validation (always)
        dry_run_result = await self._dry_run(candidate.content)
        metrics.update(dry_run_result)

        # Stage 4: Live execution (optional, expensive — needs the runner)
        if self.config.get("evaluator", {}).get("live_execution", False) and self.runner:
            exec_result = await self._execute(candidate.content)
            metrics.update(exec_result)

        return metrics

    async def _check_syntax(self, content: str) -> Dict[str, Any]:
        """Validate pipeline YAML syntax + structure."""
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {"valid": False, "error": f"YAML parse error: {e}"}
        if not isinstance(data, dict) or "steps" not in data:
            return {"valid": False, "error": "Missing top-level 'steps' section"}
        steps = data["steps"]
        if not isinstance(steps, dict) or not steps:
            return {"valid": False, "error": "'steps' must be a non-empty mapping"}
        for name, step in steps.items():
            if not isinstance(step, dict):
                return {"valid": False, "error": f"Step '{name}' is not a mapping"}
            if "image" not in step:
                return {"valid": False, "error": f"Step '{name}' is missing 'image'"}
            if "commands" not in step or not isinstance(step.get("commands"), list):
                return {"valid": False, "error": f"Step '{name}' is missing a 'commands' list"}
        return {"valid": True}

    def _static_analysis(self, content: str, goal: EvolutionGoal) -> Dict[str, float]:
        """Perform static analysis to estimate fitness (YAML-oriented)."""
        metrics = {}

        # Parallelism analysis (woodpecker: parallel step groups / detach)
        parallel_count = len(re.findall(r"^\s*parallel\s*:", content, re.M)) + content.count("detach:")
        step_count = len(re.findall(r"^\s{2}[a-z0-9_-]+:\s*$", content, re.M))
        metrics["parallelism_score"] = min(1.0, parallel_count / max(1, step_count - 1))

        # Error handling analysis (woodpecker: when: status / failure steps)
        when_count = len(re.findall(r"^\s+when\s*:", content, re.M))
        failure_count = len(re.findall(r"status:\s*\[?[^\]]*failure", content, re.I))
        metrics["error_handling_score"] = min(1.0, (when_count + failure_count * 2) / max(1, step_count))
        metrics["failure_coverage"] = min(1.0, failure_count / max(1, step_count))

        # Resource constraints analysis
        has_limits = "volumes" in content or "memory" in content.lower() or "cpu" in content.lower()
        has_cleanup = "prune" in content or "rm -rf" in content or "cleanup" in content
        metrics["resource_efficiency"] = (0.5 if has_limits else 0.0) + (0.5 if has_cleanup else 0.0)
        metrics["cleanup_score"] = 1.0 if has_cleanup else 0.0
        metrics["constraint_score"] = 1.0 if has_limits else 0.0

        # Security analysis (woodpecker: from_secret / secrets)
        has_secrets = "from_secret" in content or "secrets:" in content
        no_hardcoded = not re.search(
            r"(password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]", content, re.I
        )
        metrics["security_score"] = (0.5 if has_secrets else 0.0) + (0.5 if no_hardcoded else 0.0)
        metrics["secrets_handling"] = 1.0 if has_secrets else 0.0

        # Observability analysis
        has_echo = content.count("echo ") > 2
        has_status = "status:" in content
        metrics["logging_score"] = 0.5 if has_echo else 0.0
        metrics["notification_score"] = 0.5 if has_status else 0.0

        # Complexity penalty
        lines = len(content.split("\n"))
        metrics["complexity_penalty"] = max(0.0, 1.0 - (lines / 500))

        return metrics

    async def _dry_run(self, content: str) -> Dict[str, float]:
        """Local dry-run: YAML must parse (catches what the woodpecker
        compiler would reject at trigger time)."""
        try:
            data = yaml.safe_load(content)
            valid = isinstance(data, dict) and bool(data.get("steps"))
            return {"dry_run_valid": 1.0 if valid else 0.0}
        except Exception:
            return {"dry_run_valid": 0.0}

    async def _execute(self, content: str) -> Dict[str, float]:
        """Execute the pipeline via the woodpecker runner and measure."""
        if not self.runner:
            return {"duration_seconds": 0.0, "success_rate": 0.0, "execution_skipped": 1.0}
        try:
            timeout = float(self.config.get("evaluator", {}).get("execution_timeout", 300))
            result = await asyncio.to_thread(
                self.runner.run_content,
                "milady/evolve",
                content,
                timeout=timeout,
            )
            duration = result.get("duration_seconds") or 0.0
            return {
                "duration_score": max(0.0, 1.0 - (duration / timeout)),
                "success_rate": 1.0 if result.get("success") else 0.0,
            }
        except Exception as e:
            return {
                "duration_score": 0.0,
                "success_rate": 0.0,
                "execution_error": str(e),
            }


# ============================================================================
# Evolution Engine (MAP-Elites + Islands)
# ============================================================================

class AlphaEvolveEngine:
    """
    Main evolution engine implementing MAP-Elites with island populations.

    Combines:
    - Multiple island populations for diversity
    - MAP-Elites quality-diversity archive
    - LLM-based mutation and crossover
    - Cascade evaluation for efficiency
    """

    def __init__(self, config: Dict[str, Any], runner=None):
        self.config = config
        self.llm = LLMEnsemble(config)
        self.evaluator = PipelineEvaluator(config, runner=runner)
        self.redis_client = self._setup_redis()
        # Immutable skeleton root for the mechanical EVOLVE-BLOCK fence; set
        # per-evolve() run (see evolve()). When a template has markers, every
        # generated candidate is clamped so only fenced payloads may change.
        self._fence_template: Optional[str] = None

        # Evolution parameters
        evo_config = config.get("evolution", {})
        self.population_size = evo_config.get("population_size", 20)
        self.num_islands = evo_config.get("num_islands", 4)
        self.migration_interval = evo_config.get("migration_interval", 5)
        self.migration_size = evo_config.get("migration_size", 2)
        self.tournament_size = evo_config.get("tournament_size", 3)
        self.elite_ratio = evo_config.get("elite_ratio", 0.2)
        self.mutation_rate = evo_config.get("mutation_rate", 0.4)
        self.max_generations = evo_config.get("max_generations", 100)
        self.stagnation_limit = evo_config.get("stagnation_limit", 15)

    def _setup_redis(self) -> Optional[redis.Redis]:
        """Setup Redis connection for state persistence."""
        try:
            storage = self.config.get("storage", {}).get("redis", {})
            url = os.path.expandvars(storage.get("url", "redis://localhost:6379"))
            client = redis.from_url(url)
            client.ping()
            logger.info("Redis connected for evolution state")
            return client
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            return None

    async def evolve(
        self,
        template_path: str,
        goal_name: str,
        callbacks: Dict[str, Callable] = None
    ) -> Dict[str, Any]:
        """
        Run the evolution process.

        Args:
            template_path: Path to the pipeline template (.yml)
            goal_name: Name of the evolution goal
            callbacks: Optional callbacks for progress reporting

        Returns:
            Evolution results including best candidate
        """
        callbacks = callbacks or {}
        goal = EVOLUTION_GOALS.get(goal_name)
        if not goal:
            raise ValueError(f"Unknown goal: {goal_name}. Available: {list(EVOLUTION_GOALS.keys())}")

        # Load template
        template_content = Path(template_path).read_text()
        template_name = Path(template_path).stem
        # Mechanical EVOLVE-BLOCK fence root: block payloads are the only
        # mutable region; the surrounding skeleton stays byte-immutable.
        self._fence_template = template_content

        # Initialize state
        state = EvolutionState(
            evolution_id=str(uuid.uuid4()),
            template_name=template_name,
            goal=goal_name,
        )

        logger.info(f"Starting evolution: {state.evolution_id}")
        logger.info(f"Template: {template_name}, Goal: {goal_name}")

        await self._initialize_populations(state, template_content, goal)

        # Evolution loop
        generations_without_improvement = 0
        best_ever_fitness = float('-inf')

        for gen in range(self.max_generations):
            state.generation = gen
            logger.info(f"Generation {gen + 1}/{self.max_generations}")

            # Evaluate all islands
            await self._evaluate_populations(state, goal)

            # Update archive (MAP-Elites)
            self._update_archive(state)

            # Track best fitness
            current_best = self._get_best_fitness(state)
            if current_best > best_ever_fitness:
                best_ever_fitness = current_best
                generations_without_improvement = 0
                logger.info(f"New best fitness: {best_ever_fitness:.4f}")
            else:
                generations_without_improvement += 1

            # Check termination
            if generations_without_improvement >= self.stagnation_limit:
                logger.info(f"Stagnation limit reached after {gen + 1} generations")
                break

            # Migration between islands
            if gen > 0 and gen % self.migration_interval == 0:
                self._migrate(state)

            # Evolve populations
            await self._evolve_populations(state, goal, template_content)

            # Progress callback
            if "on_generation" in callbacks:
                callbacks["on_generation"](state, gen)

            # Save state periodically
            if self.redis_client and gen % 5 == 0:
                self._save_state(state)

        # Get best result
        best_candidate = self._get_best_candidate(state)

        # Save evolved template
        if best_candidate:
            output_path = self._save_evolved_template(
                template_name, best_candidate, state
            )

        # Final results
        results = {
            "evolution_id": state.evolution_id,
            "template_name": template_name,
            "goal": goal_name,
            "generations": state.generation + 1,
            "best_fitness": best_ever_fitness,
            "best_candidate": best_candidate.content if best_candidate else None,
            "archive_size": len(state.archive),
            "output_path": output_path if best_candidate else None,
            "duration_seconds": time.time() - state.start_time,
        }

        logger.info(f"Evolution complete: {results['generations']} generations, "
                   f"best fitness: {results['best_fitness']:.4f}")

        return results

    def _enforce_fence(self, content: str) -> str:
        """Clamp a candidate into the template's immutable skeleton.

        Only the EVOLVE-BLOCK payloads the template author marked may change;
        any edit the LLM makes outside them is mechanically discarded (the
        surrounding skeleton is byte-rebuilt from the template). Templates
        without markers pass through unchanged (legacy whole-file evolution).
        """
        tpl = getattr(self, "_fence_template", None)
        if not tpl:
            return content
        out, stats = evolve_fence.apply_fence(tpl, content)
        if not stats.get("fenced"):
            return content
        if stats.get("changed_payloads"):
            logger.info(
                "fence: %s block(s); adopted edits in %s payload(s)",
                stats.get("blocks"), stats.get("changed_payloads"),
            )
        return out

    async def _initialize_populations(
        self,
        state: EvolutionState,
        original_content: str,
        goal: EvolutionGoal
    ):
        """Initialize island populations."""
        state.populations = []
        island_size = self.population_size // self.num_islands

        for island_idx in range(self.num_islands):
            population = []

            # First candidate is always the original
            if island_idx == 0:
                original = Candidate(
                    id=str(uuid.uuid4()),
                    content=original_content,
                    generation=0,
                    island=island_idx,
                )
                population.append(original)

            # Generate variants
            while len(population) < island_size:
                variant_content = await self.llm.generate_mutation(
                    original_content,
                    goal,
                    {"island": island_idx},
                    temperature=0.7 + (island_idx * 0.1)  # Vary temperature by island
                )
                variant_content = self._enforce_fence(variant_content)

                variant = Candidate(
                    id=str(uuid.uuid4()),
                    content=variant_content,
                    generation=0,
                    island=island_idx,
                )
                population.append(variant)

            state.populations.append(population)

        logger.info(f"Initialized {self.num_islands} islands with "
                   f"{sum(len(p) for p in state.populations)} total candidates")

    async def _evaluate_populations(self, state: EvolutionState, goal: EvolutionGoal):
        """Evaluate fitness for all candidates."""
        for island_idx, population in enumerate(state.populations):
            for candidate in population:
                if candidate.fitness is None:
                    metrics = await self.evaluator.evaluate(candidate, goal)
                    candidate.metrics = metrics

                    # Calculate weighted fitness
                    fitness = 0.0
                    for metric_name, weight in goal.fitness_weights.items():
                        value = metrics.get(metric_name, 0.0)
                        fitness += value * weight

                    # Apply complexity penalty
                    fitness *= metrics.get("complexity_penalty", 1.0)

                    # Penalty for invalid syntax
                    if not metrics.get("syntax_valid", True):
                        fitness = -1.0

                    candidate.fitness = fitness

                    # Calculate feature vector for MAP-Elites
                    candidate.feature_vector = [
                        metrics.get("parallelism_score", 0.0),
                        metrics.get("error_handling_score", 0.0),
                        metrics.get("resource_efficiency", 0.0),
                    ]

    def _update_archive(self, state: EvolutionState):
        """Update MAP-Elites archive with best candidates per cell."""
        grid_res = self.config.get("map_elites", {}).get("grid_resolution", 20)

        for population in state.populations:
            for candidate in population:
                if candidate.fitness is None or candidate.fitness < 0:
                    continue

                # Discretize feature vector to grid cell
                cell = tuple(
                    min(grid_res - 1, max(0, int(f * grid_res)))
                    for f in candidate.feature_vector
                )

                # Update if better than current occupant
                if cell not in state.archive or candidate.fitness > state.archive[cell].fitness:
                    state.archive[cell] = candidate

    def _get_best_fitness(self, state: EvolutionState) -> float:
        """Get the best fitness across all populations."""
        best = float('-inf')
        for population in state.populations:
            for candidate in population:
                if candidate.fitness and candidate.fitness > best:
                    best = candidate.fitness
        return best

    def _get_best_candidate(self, state: EvolutionState) -> Optional[Candidate]:
        """Get the best candidate overall."""
        best = None
        best_fitness = float('-inf')

        # Check archive first
        for candidate in state.archive.values():
            if candidate.fitness and candidate.fitness > best_fitness:
                best = candidate
                best_fitness = candidate.fitness

        # Also check current populations
        for population in state.populations:
            for candidate in population:
                if candidate.fitness and candidate.fitness > best_fitness:
                    best = candidate
                    best_fitness = candidate.fitness

        return best

    def _migrate(self, state: EvolutionState):
        """Migrate best candidates between islands."""
        import random

        for i in range(self.num_islands):
            # Select random destination island
            dest = (i + 1) % self.num_islands

            # Get top candidates from source
            source_pop = sorted(
                state.populations[i],
                key=lambda c: c.fitness or float('-inf'),
                reverse=True
            )

            migrants = source_pop[:self.migration_size]

            # Add to destination (will be trimmed in evolution)
            for migrant in migrants:
                clone = Candidate(
                    id=str(uuid.uuid4()),
                    content=migrant.content,
                    generation=state.generation,
                    fitness=None,  # Re-evaluate in new context
                    island=dest,
                    parent_ids=[migrant.id],
                )
                state.populations[dest].append(clone)

        logger.debug(f"Migrated {self.migration_size} candidates between islands")

    async def _evolve_populations(
        self,
        state: EvolutionState,
        goal: EvolutionGoal,
        original_content: str
    ):
        """Evolve each island population to the next generation."""
        import random

        for island_idx, population in enumerate(state.populations):
            # Sort by fitness
            population.sort(key=lambda c: c.fitness or float('-inf'), reverse=True)

            # Keep elites
            elite_count = max(1, int(len(population) * self.elite_ratio))
            next_gen = population[:elite_count]

            # Reset fitness for re-evaluation
            for elite in next_gen:
                elite.generation = state.generation + 1
                elite.fitness = None

            island_size = self.population_size // self.num_islands

            # Generate offspring
            while len(next_gen) < island_size:
                if random.random() < self.mutation_rate:
                    # Mutation: take a parent and mutate
                    parent = self._tournament_select(population)

                    # Include error feedback if parent had issues
                    context = {
                        "island": island_idx,
                        "parent_metrics": parent.metrics,
                    }
                    if parent.metrics.get("error"):
                        context["last_error"] = parent.metrics["error"]

                    child_content = await self.llm.generate_mutation(
                        parent.content, goal, context
                    )
                else:
                    # Crossover: combine two parents (simplified: pick sections)
                    p1 = self._tournament_select(population)
                    p2 = self._tournament_select(population)
                    child_content = self._crossover(p1.content, p2.content)
                child_content = self._enforce_fence(child_content)

                child = Candidate(
                    id=str(uuid.uuid4()),
                    content=child_content,
                    generation=state.generation + 1,
                    island=island_idx,
                )
                next_gen.append(child)

            state.populations[island_idx] = next_gen

    def _tournament_select(self, population: List[Candidate]) -> Candidate:
        """Tournament selection."""
        import random
        tournament = random.sample(
            population,
            min(self.tournament_size, len(population))
        )
        return max(tournament, key=lambda c: c.fitness or float('-inf'))

    def _crossover(self, content1: str, content2: str) -> str:
        """Simple crossover by combining stages from both parents."""
        import random

        # Extract stages from both
        stage_pattern = r"(stage\s*\([^)]+\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})"

        stages1 = re.findall(stage_pattern, content1, re.DOTALL)
        stages2 = re.findall(stage_pattern, content2, re.DOTALL)

        if not stages1 or not stages2:
            return random.choice([content1, content2])

        # Mix stages
        combined_stages = []
        for s1, s2 in zip(stages1, stages2):
            combined_stages.append(random.choice([s1, s2]))

        # Rebuild pipeline with mixed stages
        # This is simplified; in practice would need more careful reconstruction
        return random.choice([content1, content2])

    def _save_evolved_template(
        self,
        template_name: str,
        candidate: Candidate,
        state: EvolutionState
    ) -> str:
        """Save the evolved template to disk."""
        backup_dir = Path(self.config.get("storage", {}).get("backup_dir", "evolved_templates"))
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{template_name}_evolved_{state.goal}_{timestamp}.yml"
        output_path = backup_dir / filename

        # Add evolution metadata as header comment
        header = f"""# Evolved by MiladyOS AlphaEvolve
# Evolution ID: {state.evolution_id}
# Goal: {state.goal}
# Generations: {state.generation + 1}
# Fitness: {candidate.fitness:.4f}
# Timestamp: {timestamp}

"""
        output_path.write_text(header + candidate.content)

        logger.info(f"Saved evolved template: {output_path}")
        return str(output_path)

    def _save_state(self, state: EvolutionState):
        """Save evolution state to Redis."""
        if not self.redis_client:
            return

        prefix = self.config.get("storage", {}).get("redis", {}).get("prefix", "miladyos:evolve:")
        key = f"{prefix}state:{state.evolution_id}"

        # Serialize state (simplified)
        state_data = {
            "evolution_id": state.evolution_id,
            "template_name": state.template_name,
            "goal": state.goal,
            "generation": state.generation,
            "best_fitness": state.best_fitness,
            "archive_size": len(state.archive),
            "start_time": state.start_time,
        }

        self.redis_client.set(key, json.dumps(state_data))
        self.redis_client.expire(key, 86400)  # 24 hour TTL


# ============================================================================
# CLI Interface
# ============================================================================

def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "configs" / "evolve_default.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Expand environment variables
    def expand_env(obj):
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        elif isinstance(obj, dict):
            return {k: expand_env(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_env(v) for v in obj]
        return obj

    return expand_env(config)


@click.group()
def cli():
    """MiladyOS AlphaEvolve - Evolutionary Pipeline Optimization"""
    pass


@cli.command()
@click.option("--template", "-t", required=True, help="Template name or path")
@click.option("--goal", "-g", default="reliability",
              type=click.Choice(list(EVOLUTION_GOALS.keys())),
              help="Evolution goal")
@click.option("--config", "-c", default=None, help="Config file path")
@click.option("--generations", "-n", default=None, type=int, help="Max generations")
def evolve(template: str, goal: str, config: str, generations: int):
    """Evolve a Woodpecker CI pipeline template."""
    config_data = load_config(config)

    if generations:
        config_data["evolution"]["max_generations"] = generations

    # Resolve template path
    template_path = Path(template)
    if not template_path.exists():
        template_path = Path("templates") / f"{template}.yml"
    if not template_path.exists():
        raise click.ClickException(f"Template not found: {template}")

    from woodpecker_client import WoodpeckerClient
    engine = AlphaEvolveEngine(config_data, runner=WoodpeckerClient())

    async def run():
        return await engine.evolve(str(template_path), goal)

    results = asyncio.run(run())

    click.echo("\n" + "=" * 60)
    click.echo("EVOLUTION COMPLETE")
    click.echo("=" * 60)
    click.echo(f"Evolution ID: {results['evolution_id']}")
    click.echo(f"Generations: {results['generations']}")
    click.echo(f"Best Fitness: {results['best_fitness']:.4f}")
    click.echo(f"Archive Size: {results['archive_size']}")
    click.echo(f"Duration: {results['duration_seconds']:.1f}s")
    if results.get("output_path"):
        click.echo(f"Output: {results['output_path']}")


@cli.command()
def goals():
    """List available evolution goals."""
    click.echo("\nAvailable Evolution Goals:\n")
    for name, goal in EVOLUTION_GOALS.items():
        click.echo(f"  {name}")
        click.echo(f"    {goal.description}")
        click.echo(f"    Weights: {goal.fitness_weights}")
        click.echo()


@cli.command()
@click.option("--path", "-p", default="templates", help="Templates directory")
def templates(path: str):
    """List available templates."""
    templates_dir = Path(path)
    if not templates_dir.exists():
        raise click.ClickException(f"Directory not found: {path}")

    click.echo(f"\nTemplates in {path}:\n")
    for f in sorted(templates_dir.glob("*.yml")):
        content = f.read_text()
        has_evolve = "EVOLVE-BLOCK" in content
        marker = "✓" if has_evolve else " "
        click.echo(f"  [{marker}] {f.stem}")

    click.echo("\n  [✓] = Has EVOLVE-BLOCK markers")


if __name__ == "__main__":
    cli()
