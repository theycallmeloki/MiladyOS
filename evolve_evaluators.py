#!/usr/bin/env python3
"""
MiladyOS AlphaEvolve - Pipeline Evaluators

Cascade evaluation system for Woodpecker CI pipelines:
1. Syntax validation (fast, local)
2. Static analysis (fast, local)
3. Dry run validation (local YAML structural check)
4. Live execution (slow, runs the pipeline via the woodpecker runner)

Each stage filters out bad candidates early to save compute.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import colorlog
import yaml

logger = colorlog.getLogger("miladyos-evaluators")


# ============================================================================
# Evaluator Base
# ============================================================================

@dataclass
class EvaluationResult:
    """Result from an evaluation stage."""
    passed: bool
    score: float
    metrics: Dict[str, float]
    errors: List[str]
    warnings: List[str]
    duration_ms: float


class BaseEvaluator(ABC):
    """Base class for pipeline evaluators."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get("timeout", 30)

    @abstractmethod
    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        """Evaluate the pipeline content."""
        pass


# ============================================================================
# Syntax Evaluator
# ============================================================================

class SyntaxEvaluator(BaseEvaluator):
    """
    Fast local syntax validation for Woodpecker pipeline YAML.

    Checks:
    - YAML parses cleanly
    - Required structure (steps; per-step image and commands)
    - No hardcoded secrets
    """

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        try:
            data = yaml.safe_load(content)
        except Exception as e:
            return EvaluationResult(
                passed=False,
                score=0.0,
                metrics={
                    "syntax_errors": 1,
                    "syntax_warnings": 0,
                    "line_count": len(content.split("\n")),
                    "stage_count": 0,
                },
                errors=[f"YAML parse error: {e}"],
                warnings=[],
                duration_ms=(time.time() - start) * 1000,
            )

        if not isinstance(data, dict) or "steps" not in data or not isinstance(data.get("steps"), dict):
            errors.append("Missing top-level 'steps' mapping")
        else:
            for name, step in data["steps"].items():
                if not isinstance(step, dict):
                    errors.append(f"Step '{name}' is not a mapping")
                    continue
                if "image" not in step:
                    errors.append(f"Step '{name}' is missing 'image'")
                if "commands" not in step or not isinstance(step.get("commands"), list):
                    errors.append(f"Step '{name}' is missing a 'commands' list")

        if re.search(r"(password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]", content, re.I):
            errors.append("Hardcoded secret detected")

        if "sleep " in content and "sleep 0" not in content:
            warnings.append("Sleep usage — prefer woodpecker retries/backoff where possible")

        # Calculate metrics
        metrics["syntax_errors"] = len(errors)
        metrics["syntax_warnings"] = len(warnings)
        metrics["line_count"] = len(content.split("\n"))
        metrics["stage_count"] = len(data.get("steps", {})) if isinstance(data, dict) else 0

        passed = len(errors) == 0
        score = 1.0 if passed else 0.0

        return EvaluationResult(
            passed=passed,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )


# ============================================================================
# Static Analysis Evaluator
# ============================================================================

class StaticAnalysisEvaluator(BaseEvaluator):
    """
    Deep static analysis for quality metrics.

    Analyzes:
    - Parallelization opportunities
    - Error handling coverage
    - Resource management
    - Security practices
    - Best practices compliance
    """

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        goal = context.get("goal", "reliability")

        # Parallelization analysis (woodpecker: parallel groups / detach)
        parallel_blocks = len(re.findall(r"^\s*parallel\s*:", content, re.M)) + content.count("detach:")
        step_count = len(re.findall(r"^\s{2}[a-z0-9_-]+:\s*$", content, re.M))
        command_count = len(re.findall(r"^\s*-\s+", content, re.M))

        metrics["parallel_blocks"] = parallel_blocks
        metrics["parallelism_ratio"] = parallel_blocks / max(1, step_count)
        metrics["parallelism_score"] = min(1.0, parallel_blocks / max(1, step_count - 1))

        # Error handling analysis (woodpecker: when / failure status steps)
        when_count = len(re.findall(r"^\s+when\s*:", content, re.M))
        failure_count = len(re.findall(r"status:\s*\[?[^\]]*failure", content, re.I))

        metrics["when_blocks"] = when_count
        metrics["failure_handlers"] = failure_count
        metrics["error_handling_score"] = min(1.0, (when_count + failure_count * 2) / max(1, step_count))
        metrics["retry_coverage"] = min(1.0, failure_count / max(1, step_count))
        metrics["timeout_coverage"] = min(1.0, when_count / max(1, step_count))

        # Resource management (woodpecker: volumes / cleanup steps)
        has_cleanup = any(x in content for x in ["cleanup", "prune", "rm -rf"])
        has_docker_prune = "docker system prune" in content or "docker image prune" in content
        has_resource_limits = "volumes:" in content or "memory" in content.lower() or "cpu" in content.lower()

        metrics["has_cleanup"] = 1.0 if has_cleanup else 0.0
        metrics["has_docker_cleanup"] = 1.0 if has_docker_prune else 0.0
        metrics["has_resource_limits"] = 1.0 if has_resource_limits else 0.0
        metrics["resource_efficiency"] = (
            (0.4 if has_cleanup else 0.0) +
            (0.3 if has_docker_prune else 0.0) +
            (0.3 if has_resource_limits else 0.0)
        )

        # Security analysis (woodpecker: from_secret / secrets)
        uses_credentials = "from_secret" in content or "secrets:" in content
        uses_env_vars = "variables:" in content
        no_hardcoded_secrets = not re.search(
            r"(password|secret|token|api[_-]?key)\s*[:=]\s*['\"][^$][^'\"]+['\"]",
            content, re.I
        )

        metrics["uses_credentials"] = 1.0 if uses_credentials else 0.0
        metrics["uses_env_vars"] = 1.0 if uses_env_vars else 0.0
        metrics["no_hardcoded_secrets"] = 1.0 if no_hardcoded_secrets else 0.0
        metrics["security_score"] = (
            (0.4 if uses_credentials else 0.0) +
            (0.2 if uses_env_vars else 0.0) +
            (0.4 if no_hardcoded_secrets else 0.0)
        )

        if not no_hardcoded_secrets:
            errors.append("Potential hardcoded secrets detected")

        # Best practices
        has_post = "when:" in content and "status:" in content
        has_options = "skip_clone" in content or "volumes:" in content
        has_parameters = "variables:" in content
        uses_shallow_clone = "depth" in content or "filter:" in content

        metrics["has_post_actions"] = 1.0 if has_post else 0.0
        metrics["has_options"] = 1.0 if has_options else 0.0
        metrics["uses_shallow_clone"] = 1.0 if uses_shallow_clone else 0.0

        # Caching analysis
        has_cache = any(x in content.lower() for x in ["cache", "plugin", "volume"])
        has_npm_ci = "npm ci" in content
        has_pip_cache = "--cache-dir" in content or "PIP_CACHE_DIR" in content

        metrics["has_caching"] = 1.0 if has_cache or has_npm_ci else 0.0
        metrics["speed_optimizations"] = (
            (0.3 if uses_shallow_clone else 0.0) +
            (0.3 if has_cache else 0.0) +
            (0.2 if has_npm_ci else 0.0) +
            (0.2 if parallel_blocks > 0 else 0.0)
        )

        # Complexity penalty (nesting via indentation)
        lines = len(content.split("\n"))
        indents = [len(line) - len(line.lstrip()) for line in content.split("\n") if line.strip()]
        nesting_depth = max(indents) // 2 if indents else 0

        metrics["complexity_lines"] = lines
        metrics["max_nesting"] = nesting_depth
        metrics["complexity_penalty"] = max(0.5, 1.0 - (lines / 500) - (nesting_depth / 20))

        # Warnings for missing best practices
        if not has_post:
            warnings.append("No when/status steps for failure handling")
        if not has_cleanup:
            warnings.append("No cleanup step (prune/rm)")
        if command_count > 3 and failure_count == 0:
            warnings.append("Multiple commands without failure handling")

        # Calculate overall score based on goal
        if goal == "speed":
            score = (
                metrics["parallelism_score"] * 0.3 +
                metrics["speed_optimizations"] * 0.4 +
                metrics["complexity_penalty"] * 0.3
            )
        elif goal == "reliability":
            score = (
                metrics["error_handling_score"] * 0.4 +
                metrics["retry_coverage"] * 0.3 +
                metrics["timeout_coverage"] * 0.2 +
                metrics["has_post_actions"] * 0.1
            )
        elif goal == "resources":
            score = (
                metrics["resource_efficiency"] * 0.5 +
                metrics["has_caching"] * 0.3 +
                metrics["complexity_penalty"] * 0.2
            )
        elif goal == "security":
            score = metrics["security_score"]
        else:
            # Balanced score
            score = (
                metrics.get("error_handling_score", 0) * 0.25 +
                metrics.get("parallelism_score", 0) * 0.2 +
                metrics.get("resource_efficiency", 0) * 0.2 +
                metrics.get("security_score", 0) * 0.2 +
                metrics.get("complexity_penalty", 0) * 0.15
            )

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )


# ============================================================================
# Dry Run Evaluator
# ============================================================================

class DryRunEvaluator(BaseEvaluator):
    """
    Local dry-run: validates that the pipeline YAML parses and has the
    shape the woodpecker compiler requires (steps, images, commands).
    Catches candidates the compiler would reject at trigger time.
    """

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        try:
            result = await asyncio.to_thread(self._validate_pipeline, content)
        except Exception as e:
            errors.append(f"Dry run failed: {str(e)}")
            metrics["dry_run_error"] = 1.0
            score = 0.0
            return EvaluationResult(
                passed=False,
                score=score,
                metrics=metrics,
                errors=errors,
                warnings=warnings,
                duration_ms=(time.time() - start) * 1000,
            )

        if result["valid"]:
            metrics["dry_run_valid"] = 1.0
            score = 1.0
        else:
            metrics["dry_run_valid"] = 0.0
            errors.extend(result.get("errors", ["Validation failed"]))
            score = 0.0

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )

    def _validate_pipeline(self, content: str) -> Dict[str, Any]:
        """Local structural validation (mirrors the woodpecker compiler
        checks: parseable YAML, steps mapping, per-step image + commands)."""
        try:
            data = yaml.safe_load(content)
        except Exception as e:
            return {"valid": False, "errors": [f"YAML parse error: {e}"]}
        if not isinstance(data, dict) or not isinstance(data.get("steps"), dict):
            return {"valid": False, "errors": ["Missing top-level 'steps' mapping"]}
        for name, step in data["steps"].items():
            if not isinstance(step, dict):
                return {"valid": False, "errors": [f"Step '{name}' is not a mapping"]}
            if "image" not in step:
                return {"valid": False, "errors": [f"Step '{name}' is missing 'image'"]}
            if "commands" not in step or not isinstance(step.get("commands"), list):
                return {"valid": False, "errors": [f"Step '{name}' is missing a 'commands' list"]}
        return {"valid": True}


# ============================================================================
# Live Execution Evaluator
# ============================================================================

class ExecutionEvaluator(BaseEvaluator):
    """
    Execute pipeline via the woodpecker runner and measure real metrics.

    Runs the candidate on the local woodpecker agent (milady/evolve repo)
    and extracts:
    - Execution duration
    - Success/failure
    - Step exit codes
    - Error messages
    """

    def __init__(self, config: Dict[str, Any], runner=None):
        super().__init__(config)
        self.runner = runner
        self.timeout = config.get("timeout", 300)  # 5 minute default

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        if not self.runner:
            return EvaluationResult(
                passed=True,
                score=0.5,  # Uncertain without execution
                metrics={"skipped": 1.0},
                errors=[],
                warnings=["No pipeline runner available for live execution"],
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            result = await asyncio.to_thread(
                self._execute_pipeline,
                content,
            )

            metrics["duration_seconds"] = result.get("duration_seconds", 0.0)
            metrics["success_rate"] = 1.0 if result.get("success") else 0.0

            if result.get("success"):
                score = 1.0
            else:
                score = 0.0
                errors.extend(result.get("errors", ["Execution failed"]))

        except asyncio.TimeoutError:
            errors.append(f"Execution timeout after {self.timeout}s")
            metrics["timeout"] = 1.0
            score = 0.0
        except Exception as e:
            errors.append(f"Execution error: {str(e)}")
            score = 0.0

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )

    def _execute_pipeline(self, content: str) -> Dict[str, Any]:
        """Execute the pipeline on the local woodpecker runner."""
        try:
            result = self.runner.run_content(
                "milady/evolve",
                content,
                timeout=self.timeout,
            )
            return {
                "success": result.get("success", False),
                "duration_seconds": result.get("duration_seconds") or 0.0,
                "errors": [] if result.get("success") else [f"pipeline status: {result.get('status')}"],
            }
        except Exception as e:
            return {
                "success": False,
                "duration_seconds": 0.0,
                "errors": [str(e)],
            }


# ============================================================================
# Cascade Evaluator (Orchestrator)
# ============================================================================

class CascadeEvaluator:
    """
    Orchestrates cascade evaluation through multiple stages.

    Runs evaluators in order of cost (fast → slow), stopping early
    if a candidate fails critical checks.
    """

    def __init__(self, config: Dict[str, Any], runner=None):
        self.config = config
        self.evaluators = [
            ("syntax", SyntaxEvaluator(config), 1.0, True),  # name, evaluator, weight, required
            ("static", StaticAnalysisEvaluator(config), 1.0, False),
            ("dry_run", DryRunEvaluator(config), 0.5, False),
            ("execution", ExecutionEvaluator(config, runner), 2.0, False),
        ]

        # Filter based on config
        cascade_config = config.get("evaluator", {}).get("cascade", [])
        if cascade_config:
            enabled = {c["name"] for c in cascade_config}
            self.evaluators = [
                (name, e, w, r) for name, e, w, r in self.evaluators
                if name in enabled
            ]

    async def evaluate(
        self,
        content: str,
        context: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Run cascade evaluation.

        Returns:
            Tuple of (fitness_score, all_metrics)
        """
        all_metrics = {}
        total_score = 0.0
        total_weight = 0.0

        for name, evaluator, weight, required in self.evaluators:
            logger.debug(f"Running {name} evaluator...")

            try:
                result = await evaluator.evaluate(content, context)

                # Store metrics with evaluator prefix
                for k, v in result.metrics.items():
                    all_metrics[f"{name}_{k}"] = v

                all_metrics[f"{name}_score"] = result.score
                all_metrics[f"{name}_passed"] = 1.0 if result.passed else 0.0
                all_metrics[f"{name}_duration_ms"] = result.duration_ms

                # Record errors and warnings
                if result.errors:
                    all_metrics[f"{name}_errors"] = result.errors
                if result.warnings:
                    all_metrics[f"{name}_warnings"] = result.warnings

                # Update weighted score
                total_score += result.score * weight
                total_weight += weight

                # Early termination on required stage failure
                if required and not result.passed:
                    logger.debug(f"Failed required stage: {name}")
                    all_metrics["early_termination"] = name
                    break

            except Exception as e:
                logger.error(f"Evaluator {name} failed: {e}")
                all_metrics[f"{name}_error"] = str(e)
                if required:
                    break

        # Calculate final fitness
        fitness = total_score / total_weight if total_weight > 0 else 0.0

        return fitness, all_metrics


# ============================================================================
# Utility Functions
# ============================================================================

def extract_metrics_from_console(console_output: str) -> Dict[str, float]:
    """Extract generic metrics from a pipeline console output."""
    metrics = {}

    # Error/warning counts
    metrics["error_count"] = len(re.findall(r"\[ERROR\]|\bERROR\b|\berror:\b", console_output, re.I))
    metrics["warning_count"] = len(re.findall(r"\[WARN\]|\bWARNING\b|\bwarning:\b", console_output, re.I))

    # Exit-code markers (ad-hoc execute_command format)
    exit_match = re.search(r"EXIT CODE:\s*(\d+)", console_output)
    if exit_match:
        metrics["exit_code"] = float(exit_match.group(1))
        metrics["success"] = 1.0 if exit_match.group(1) == "0" else 0.0

    # Step markers (woodpecker xtrace style "+ command")
    metrics["command_count"] = float(len(re.findall(r"^\s*\+ ", console_output, re.M)))

    return metrics
