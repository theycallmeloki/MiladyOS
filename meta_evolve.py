#!/usr/bin/env python3
"""
MiladyOS Meta-Evolution - Self-Improving Evolution System

This module enables recursive evolution where:
1. The evolution system can optimize its own parameters
2. Evolved templates can spawn new EVOLVE-BLOCK markers
3. Evolution chains can be created for continuous improvement
4. The fitness functions themselves can be evolved

"The snake eats its own tail" - Ouroboros principle applied to CI/CD
"""

import asyncio
import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import colorlog
import yaml

logger = colorlog.getLogger("miladyos-meta-evolve")


# ============================================================================
# Meta-Evolution Data Structures
# ============================================================================

@dataclass
class EvolutionChain:
    """Represents a chain of evolution runs."""
    chain_id: str
    template_name: str
    evolutions: List[Dict[str, Any]] = field(default_factory=list)
    total_fitness_improvement: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class MetaCandidate:
    """A candidate configuration for meta-evolution."""
    id: str
    config: Dict[str, Any]
    fitness: Optional[float] = None
    evaluation_results: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class EvolveBlockSpec:
    """Specification for an EVOLVE-BLOCK in a template."""
    block_type: str  # e.g., "build", "test", "deploy"
    language: str  # e.g., "javascript", "python", "docker"
    goals: List[str]  # e.g., ["speed", "reliability"]
    complexity: str  # "low", "medium", "high"
    constraints: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Recursive Evolution Engine
# ============================================================================

class MetaEvolutionEngine:
    """
    Meta-evolution engine that can:
    1. Evolve evolution parameters (population size, mutation rate, etc.)
    2. Generate new EVOLVE-BLOCK markers in evolved code
    3. Chain multiple evolution runs together
    4. Learn optimal evolution strategies per template type
    """

    def __init__(self, base_config: Dict[str, Any]):
        self.base_config = base_config
        self.config_space = self._define_config_space()
        self.strategy_memory: Dict[str, Dict[str, Any]] = {}

    def _define_config_space(self) -> Dict[str, Dict[str, Any]]:
        """Define the space of evolvable configuration parameters."""
        return {
            "population_size": {
                "type": "int",
                "min": 5,
                "max": 50,
                "default": 20,
            },
            "num_islands": {
                "type": "int",
                "min": 1,
                "max": 8,
                "default": 4,
            },
            "mutation_rate": {
                "type": "float",
                "min": 0.1,
                "max": 0.8,
                "default": 0.4,
            },
            "elite_ratio": {
                "type": "float",
                "min": 0.1,
                "max": 0.5,
                "default": 0.2,
            },
            "tournament_size": {
                "type": "int",
                "min": 2,
                "max": 7,
                "default": 3,
            },
            "migration_interval": {
                "type": "int",
                "min": 2,
                "max": 20,
                "default": 5,
            },
            "stagnation_limit": {
                "type": "int",
                "min": 5,
                "max": 30,
                "default": 15,
            },
            "llm_temperature": {
                "type": "float",
                "min": 0.3,
                "max": 1.2,
                "default": 0.8,
            },
        }

    def generate_random_config(self) -> Dict[str, Any]:
        """Generate a random configuration within the defined space."""
        config = {}
        for param, spec in self.config_space.items():
            if spec["type"] == "int":
                config[param] = random.randint(spec["min"], spec["max"])
            elif spec["type"] == "float":
                config[param] = random.uniform(spec["min"], spec["max"])
        return config

    def mutate_config(self, config: Dict[str, Any], mutation_strength: float = 0.3) -> Dict[str, Any]:
        """Mutate a configuration with given strength."""
        mutated = config.copy()

        for param, spec in self.config_space.items():
            if random.random() < mutation_strength:
                if spec["type"] == "int":
                    delta = int((spec["max"] - spec["min"]) * 0.2)
                    mutated[param] = max(spec["min"], min(spec["max"],
                        mutated.get(param, spec["default"]) + random.randint(-delta, delta)))
                elif spec["type"] == "float":
                    delta = (spec["max"] - spec["min"]) * 0.2
                    mutated[param] = max(spec["min"], min(spec["max"],
                        mutated.get(param, spec["default"]) + random.uniform(-delta, delta)))

        return mutated

    async def meta_evolve(
        self,
        template_path: str,
        goal: str,
        meta_generations: int = 5,
        evaluations_per_config: int = 3
    ) -> Dict[str, Any]:
        """
        Run meta-evolution to find optimal evolution parameters.

        This runs multiple evolution attempts with different configurations
        and learns which parameters work best for this template type.
        """
        from alpha_evolve import AlphaEvolveEngine

        logger.info(f"Starting meta-evolution for {template_path}")

        # Initialize population of configurations
        population: List[MetaCandidate] = []
        for _ in range(5):
            config = self.generate_random_config()
            candidate = MetaCandidate(
                id=str(uuid.uuid4()),
                config=config
            )
            population.append(candidate)

        best_config = None
        best_fitness = float('-inf')

        for meta_gen in range(meta_generations):
            logger.info(f"Meta-generation {meta_gen + 1}/{meta_generations}")

            # Evaluate each configuration
            for candidate in population:
                if candidate.fitness is not None:
                    continue

                # Run evolution with this config multiple times
                fitness_scores = []
                for eval_run in range(evaluations_per_config):
                    try:
                        # Create engine with candidate config
                        full_config = self._merge_config(candidate.config)
                        engine = AlphaEvolveEngine(full_config)

                        # Run a short evolution
                        full_config["evolution"]["max_generations"] = 10  # Quick test
                        result = await engine.evolve(template_path, goal)

                        fitness_scores.append(result.get("best_fitness", 0.0))
                        candidate.evaluation_results.append(result)

                    except Exception as e:
                        logger.warning(f"Evaluation failed: {e}")
                        fitness_scores.append(0.0)

                # Average fitness across runs
                candidate.fitness = sum(fitness_scores) / len(fitness_scores) if fitness_scores else 0.0

                if candidate.fitness > best_fitness:
                    best_fitness = candidate.fitness
                    best_config = candidate.config
                    logger.info(f"New best config found: fitness={best_fitness:.4f}")

            # Evolve configurations for next generation
            population.sort(key=lambda c: c.fitness or 0, reverse=True)

            # Keep top configs and mutate
            new_population = population[:2]  # Elites
            while len(new_population) < 5:
                parent = random.choice(population[:3])
                mutated_config = self.mutate_config(parent.config)
                child = MetaCandidate(
                    id=str(uuid.uuid4()),
                    config=mutated_config
                )
                new_population.append(child)

            population = new_population

        # Store learned strategy
        template_type = self._classify_template(template_path)
        self.strategy_memory[f"{template_type}:{goal}"] = best_config

        return {
            "best_config": best_config,
            "best_fitness": best_fitness,
            "meta_generations": meta_generations,
            "template_type": template_type,
        }

    def _merge_config(self, evolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """Merge evolved parameters into base config."""
        config = self.base_config.copy()

        if "evolution" not in config:
            config["evolution"] = {}

        for param, value in evolved_params.items():
            if param == "llm_temperature":
                if "llm" not in config:
                    config["llm"] = {}
                if "primary" not in config["llm"]:
                    config["llm"]["primary"] = {}
                config["llm"]["primary"]["temperature"] = value
            else:
                config["evolution"][param] = value

        return config

    def _classify_template(self, template_path: str) -> str:
        """Classify template type based on content."""
        content = Path(template_path).read_text().lower()

        if "docker" in content:
            return "docker"
        elif "npm" in content or "node" in content:
            return "javascript"
        elif "pip" in content or "python" in content:
            return "python"
        elif "mvn" in content or "gradle" in content:
            return "java"
        elif "kubectl" in content or "helm" in content:
            return "kubernetes"
        else:
            return "generic"


# ============================================================================
# EVOLVE-BLOCK Generator
# ============================================================================

class EvolveBlockGenerator:
    """
    Generates new EVOLVE-BLOCK markers for templates.

    This enables recursive evolution by identifying optimization
    opportunities in already-evolved templates.
    """

    BLOCK_PATTERNS = {
        "build": {
            "indicators": ["npm run build", "make", "go build", "cargo build", "mvn package"],
            "default_goals": ["speed", "reliability"],
        },
        "test": {
            "indicators": ["npm test", "pytest", "go test", "cargo test", "mvn test"],
            "default_goals": ["reliability", "speed"],
        },
        "deploy": {
            "indicators": ["kubectl apply", "helm", "docker push", "aws ", "gcloud"],
            "default_goals": ["reliability", "security"],
        },
        "lint": {
            "indicators": ["eslint", "pylint", "golangci-lint", "clippy"],
            "default_goals": ["speed"],
        },
        "security": {
            "indicators": ["trivy", "snyk", "bandit", "semgrep"],
            "default_goals": ["security", "reliability"],
        },
    }

    def analyze_template(self, content: str) -> List[EvolveBlockSpec]:
        """Analyze a template and identify potential EVOLVE-BLOCK candidates."""
        specs = []

        # Find stages without EVOLVE-BLOCK markers
        import re

        # Find all stage blocks
        stage_pattern = r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
        stages = re.findall(stage_pattern, content, re.DOTALL)

        for stage_name, stage_content in stages:
            # Skip if already has EVOLVE-BLOCK
            if "EVOLVE-BLOCK" in stage_content:
                continue

            # Classify the stage
            block_type = self._classify_stage(stage_name, stage_content)
            language = self._detect_language(stage_content)
            complexity = self._estimate_complexity(stage_content)

            if block_type:
                spec = EvolveBlockSpec(
                    block_type=block_type,
                    language=language,
                    goals=self.BLOCK_PATTERNS.get(block_type, {}).get("default_goals", ["reliability"]),
                    complexity=complexity,
                )
                specs.append(spec)

        return specs

    def inject_evolve_blocks(self, content: str, specs: List[EvolveBlockSpec]) -> str:
        """Inject EVOLVE-BLOCK markers into a template."""
        import re

        modified = content

        for spec in specs:
            # Find matching stage
            pattern = rf"(stage\s*\(\s*['\"][^'\"]*{spec.block_type}[^'\"]*['\"]\s*\)\s*\{{)"

            def replacement(match):
                metadata = json.dumps({
                    "type": spec.block_type,
                    "language": spec.language,
                    "complexity": spec.complexity,
                    "optimization_priority": spec.goals,
                }, indent=2)

                return f"""// EVOLVE-BLOCK-START: {metadata}
{match.group(1)}"""

            modified = re.sub(pattern, replacement, modified, flags=re.IGNORECASE, count=1)

            # Add END marker (simplified - would need proper brace matching in production)
            # For now, we'll add a comment suggesting where to add it

        return modified

    def _classify_stage(self, name: str, content: str) -> Optional[str]:
        """Classify a stage based on its name and content."""
        combined = f"{name} {content}".lower()

        for block_type, config in self.BLOCK_PATTERNS.items():
            for indicator in config["indicators"]:
                if indicator.lower() in combined:
                    return block_type

        return None

    def _detect_language(self, content: str) -> str:
        """Detect the primary language/toolchain."""
        content_lower = content.lower()

        if "npm" in content_lower or "node" in content_lower or "yarn" in content_lower:
            return "javascript"
        elif "pip" in content_lower or "python" in content_lower or "pytest" in content_lower:
            return "python"
        elif "go " in content_lower or "go build" in content_lower:
            return "go"
        elif "cargo" in content_lower or "rustc" in content_lower:
            return "rust"
        elif "mvn" in content_lower or "gradle" in content_lower:
            return "java"
        elif "docker" in content_lower:
            return "docker"
        else:
            return "shell"

    def _estimate_complexity(self, content: str) -> str:
        """Estimate the complexity of a stage."""
        lines = len(content.strip().split("\n"))
        commands = content.count("sh ") + content.count("sh'") + content.count('sh"')

        if lines > 20 or commands > 5:
            return "high"
        elif lines > 10 or commands > 2:
            return "medium"
        else:
            return "low"


# ============================================================================
# Evolution Chain Manager
# ============================================================================

class EvolutionChainManager:
    """
    Manages chains of evolution runs for continuous improvement.

    Enables:
    - Scheduled re-evolution of templates
    - Progressive optimization across multiple goals
    - Learning from past evolution attempts
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.chains: Dict[str, EvolutionChain] = {}

    async def create_chain(
        self,
        template_name: str,
        goals: List[str],
        interval_hours: int = 24
    ) -> EvolutionChain:
        """Create a new evolution chain for continuous improvement."""
        chain = EvolutionChain(
            chain_id=str(uuid.uuid4()),
            template_name=template_name,
        )

        self.chains[chain.chain_id] = chain

        if self.redis:
            self.redis.hset(
                f"miladyos:evolve:chain:{chain.chain_id}",
                mapping={
                    "template_name": template_name,
                    "goals": json.dumps(goals),
                    "interval_hours": interval_hours,
                    "created_at": chain.created_at,
                }
            )

        return chain

    async def run_chain_evolution(
        self,
        chain_id: str,
        current_goal_index: int = 0
    ) -> Dict[str, Any]:
        """Run the next evolution in a chain."""
        from alpha_evolve import AlphaEvolveEngine, load_config

        chain = self.chains.get(chain_id)
        if not chain:
            raise ValueError(f"Chain {chain_id} not found")

        # Get chain config from Redis if available
        goals = ["reliability", "speed", "resources"]  # Default rotation
        if self.redis:
            chain_data = self.redis.hgetall(f"miladyos:evolve:chain:{chain_id}")
            if chain_data and b"goals" in chain_data:
                goals = json.loads(chain_data[b"goals"])

        # Select current goal (rotate through goals)
        goal = goals[current_goal_index % len(goals)]

        # Find the latest evolved version or use original
        template_path = self._get_latest_template(chain.template_name)

        # Run evolution
        config = load_config()
        engine = AlphaEvolveEngine(config)
        result = await engine.evolve(str(template_path), goal)

        # Record in chain
        chain.evolutions.append({
            "goal": goal,
            "result": result,
            "timestamp": time.time(),
        })

        if result.get("best_fitness", 0) > 0:
            chain.total_fitness_improvement += result["best_fitness"]

        return result

    def _get_latest_template(self, template_name: str) -> Path:
        """Get the latest version of a template (evolved or original)."""
        evolved_dir = Path("evolved_templates")

        if evolved_dir.exists():
            # Find most recent evolved version
            evolved_files = list(evolved_dir.glob(f"{template_name}_evolved_*.Jenkinsfile"))
            if evolved_files:
                return max(evolved_files, key=lambda f: f.stat().st_mtime)

        # Fall back to original
        return Path("templates") / f"{template_name}.Jenkinsfile"


# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """CLI interface for meta-evolution."""
    import click

    @click.group()
    def cli():
        """MiladyOS Meta-Evolution - Self-improving evolution system"""
        pass

    @cli.command()
    @click.option("--template", "-t", required=True, help="Template to meta-evolve")
    @click.option("--goal", "-g", default="reliability", help="Evolution goal")
    @click.option("--meta-generations", "-m", default=5, help="Meta-evolution generations")
    def meta_evolve(template: str, goal: str, meta_generations: int):
        """Run meta-evolution to optimize evolution parameters."""
        from alpha_evolve import load_config

        config = load_config()
        engine = MetaEvolutionEngine(config)

        template_path = Path("templates") / f"{template}.Jenkinsfile"
        if not template_path.exists():
            click.echo(f"Template not found: {template}")
            return

        async def run():
            return await engine.meta_evolve(
                str(template_path), goal, meta_generations
            )

        result = asyncio.run(run())

        click.echo("\nMeta-Evolution Complete!")
        click.echo(f"Best Config: {json.dumps(result['best_config'], indent=2)}")
        click.echo(f"Best Fitness: {result['best_fitness']:.4f}")

    @cli.command()
    @click.option("--template", "-t", required=True, help="Template to analyze")
    def analyze(template: str):
        """Analyze a template for evolution opportunities."""
        template_path = Path("templates") / f"{template}.Jenkinsfile"
        if not template_path.exists():
            click.echo(f"Template not found: {template}")
            return

        content = template_path.read_text()
        generator = EvolveBlockGenerator()
        specs = generator.analyze_template(content)

        click.echo(f"\nFound {len(specs)} evolution opportunities:\n")
        for spec in specs:
            click.echo(f"  Type: {spec.block_type}")
            click.echo(f"  Language: {spec.language}")
            click.echo(f"  Complexity: {spec.complexity}")
            click.echo(f"  Suggested Goals: {spec.goals}")
            click.echo()

    @cli.command()
    @click.option("--template", "-t", required=True, help="Template to inject blocks into")
    @click.option("--output", "-o", help="Output file (default: modify in place)")
    def inject_blocks(template: str, output: str):
        """Inject EVOLVE-BLOCK markers into a template."""
        template_path = Path("templates") / f"{template}.Jenkinsfile"
        if not template_path.exists():
            click.echo(f"Template not found: {template}")
            return

        content = template_path.read_text()
        generator = EvolveBlockGenerator()

        specs = generator.analyze_template(content)
        modified = generator.inject_evolve_blocks(content, specs)

        output_path = Path(output) if output else template_path
        output_path.write_text(modified)

        click.echo(f"Injected {len(specs)} EVOLVE-BLOCK markers")
        click.echo(f"Output: {output_path}")

    cli()


if __name__ == "__main__":
    asyncio.run(main())
