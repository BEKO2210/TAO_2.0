"""
Training & Experiment Agent (Agent 10).

Plans local training runs, creates proof-of-concepts,
tracks benchmark metrics, and maintains experiment logs.

Provides experiment plans and hardware estimates.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "training_experiment_agent"
AGENT_VERSION: str = "1.0.0"


class TrainingExperimentAgent:
    """
    Agent for planning local training runs and experiments.

    Creates proof-of-concept plans, estimates hardware requirements,
    defines benchmark metrics, and maintains experiment logs for
    iterative development.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the TrainingExperimentAgent.

        Args:
            config: Configuration with optional:
                - hardware_profile: Available hardware
                - experiments_dir: Directory for experiment logs
                - default_epochs: Default training epochs
                - default_batch_size: Default batch size
        """
        self.config: dict = config
        self._status: str = "idle"
        self._hardware_profile: dict = config.get("hardware_profile", {})
        self._experiments_dir: str = config.get("experiments_dir", "./experiments")
        self._default_epochs: int = config.get("default_epochs", 3)
        self._default_batch_size: int = config.get("default_batch_size", 8)
        self._experiment_log: list[dict] = []

        logger.info(
            "TrainingExperimentAgent initialized (epochs=%d, batch=%d)",
            self._default_epochs, self._default_batch_size,
        )

    def run(self, task: dict) -> dict:
        """
        Run training experiment planning.

        Args:
            task: Dictionary with 'params' containing:
                - action: "plan", "poc", "benchmark", "log_experiment"
                - model_name: Model to experiment with
                - dataset: Dataset description
                - subnet_category: Target subnet category

        Returns:
            Experiment plan and hardware estimate
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "plan")

        logger.info("TrainingExperimentAgent: action=%s", action)

        try:
            if action == "plan":
                result = self._create_training_plan(params)
            elif action == "poc":
                result = self._create_poc_plan(params)
            elif action == "benchmark":
                result = self._create_benchmark_config(params)
            elif action == "log_experiment":
                result = self._log_experiment(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._experiment_log.append({
                "timestamp": time.time(),
                "action": action,
            })
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("TrainingExperimentAgent: failed: %s", e)
            raise

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary
        """
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "experiments": len(self._experiment_log),
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        """
        Validate task input.

        Args:
            task: Task dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(task, dict):
            return False, "Task must be a dictionary"
        params = task.get("params", {})
        action = params.get("action", "plan")
        valid_actions = ["plan", "poc", "benchmark", "log_experiment"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _create_training_plan(self, params: dict) -> dict:
        """
        Create a training plan for a model/subnet.

        Args:
            params: Training parameters

        Returns:
            Training plan dictionary
        """
        model_name = params.get("model_name", "unknown")
        dataset = params.get("dataset", "")
        subnet_category = params.get("subnet_category", "nlp")
        epochs = params.get("epochs", self._default_epochs)
        batch_size = params.get("batch_size", self._default_batch_size)

        # Estimate hardware needs
        hw_estimate = self._estimate_hardware(model_name, subnet_category, epochs, batch_size)

        # Create training steps
        steps: list[dict] = [
            {
                "step": 1,
                "title": "Data Preparation",
                "description": "Prepare and preprocess training data",
                "estimated_time": "1-2 hours",
                "artifacts": ["processed_dataset/", "data_stats.json"],
            },
            {
                "step": 2,
                "title": "Model Setup",
                "description": f"Load and configure {model_name}",
                "estimated_time": "30 minutes",
                "artifacts": ["model_config.yaml"],
            },
            {
                "step": 3,
                "title": "Training",
                "description": f"Train for {epochs} epochs with batch size {batch_size}",
                "estimated_time": f"{hw_estimate['estimated_time_hours']} hours",
                "artifacts": ["checkpoints/", "training.log"],
            },
            {
                "step": 4,
                "title": "Evaluation",
                "description": "Evaluate model on validation set",
                "estimated_time": "1 hour",
                "artifacts": ["evaluation_results.json"],
            },
            {
                "step": 5,
                "title": "Export",
                "description": "Export model for inference",
                "estimated_time": "30 minutes",
                "artifacts": ["exported_model/"],
            },
        ]

        # Check hardware compatibility
        hw_compat = self._check_hardware_compatibility(hw_estimate)

        return {
            "status": "plan_created",
            "training_plan": {
                "model_name": model_name,
                "dataset": dataset,
                "subnet_category": subnet_category,
                "epochs": epochs,
                "batch_size": batch_size,
                "steps": steps,
            },
            "hardware_estimate": hw_estimate,
            "hardware_compatible": hw_compat,
            "recommended_hyperparameters": self._get_hyperparameters(subnet_category),
            "timestamp": time.time(),
        }

    def _create_poc_plan(self, params: dict) -> dict:
        """
        Create a proof-of-concept plan.

        Args:
            params: PoC parameters

        Returns:
            PoC plan dictionary
        """
        subnet_category = params.get("subnet_category", "nlp")
        model_name = params.get("model_name", "default")

        # Simplified PoC plan
        return {
            "status": "poc_plan_created",
            "poc_plan": {
                "title": f"Proof of Concept: {model_name} for {subnet_category}",
                "description": (
                    "Minimal implementation to validate the approach "
                    "before full training"
                ),
                "steps": [
                    {
                        "id": "POC-1",
                        "title": "Minimal Dataset",
                        "description": "Create a 100-sample subset for quick iteration",
                        "estimated_time": "30 min",
                    },
                    {
                        "id": "POC-2",
                        "title": "Minimal Model",
                        "description": "Use a small model (e.g., distilbert-base)",
                        "estimated_time": "30 min",
                    },
                    {
                        "id": "POC-3",
                        "title": "Quick Training",
                        "description": "Train for 1 epoch to verify pipeline",
                        "estimated_time": "1-2 hours",
                    },
                    {
                        "id": "POC-4",
                        "title": "Validation",
                        "description": "Run inference on 10 samples",
                        "estimated_time": "30 min",
                    },
                ],
                "success_criteria": [
                    "Training completes without errors",
                    "Model produces outputs in expected format",
                    "Inference latency < 1 second per sample",
                ],
                "next_steps_on_success": [
                    "Scale to full dataset",
                    "Increase model size",
                    "Run full hyperparameter search",
                ],
            },
            "estimated_total_time": "3-4 hours",
            "timestamp": time.time(),
        }

    def _create_benchmark_config(self, params: dict) -> dict:
        """
        Create benchmark configuration.

        Args:
            params: Benchmark parameters

        Returns:
            Benchmark config dictionary
        """
        subnet_category = params.get("subnet_category", "nlp")

        metrics: list[dict] = [
            {
                "name": "training_time_per_epoch",
                "description": "Wall-clock time per training epoch",
                "unit": "minutes",
                "target": "< 60",
                "how_to_measure": "time python train.py",
            },
            {
                "name": "inference_latency",
                "description": "Time for single inference call",
                "unit": "milliseconds",
                "target": "< 500",
                "how_to_measure": "Benchmark script with 100 samples",
            },
            {
                "name": "gpu_memory_usage",
                "description": "Peak GPU memory during training",
                "unit": "GB",
                "target": "< available VRAM",
                "how_to_measure": "nvidia-smi monitoring",
            },
            {
                "name": "model_quality_score",
                "description": "Task-specific quality metric",
                "unit": "score",
                "target": "> 0.7",
                "how_to_measure": "Evaluation script",
            },
            {
                "name": "throughput",
                "description": "Samples processed per second",
                "unit": "samples/sec",
                "target": "> 10",
                "how_to_measure": "Benchmark with batch processing",
            },
        ]

        return {
            "status": "benchmark_config_created",
            "subnet_category": subnet_category,
            "metrics": metrics,
            "logging_config": {
                "log_dir": "./experiments/logs",
                "log_frequency": "per_step",
                "track": [
                    "loss",
                    "learning_rate",
                    "gpu_memory",
                    "throughput",
                    "grad_norm",
                ],
            },
            "timestamp": time.time(),
        }

    def _log_experiment(self, params: dict) -> dict:
        """
        Log an experiment result.

        Args:
            params: Experiment parameters

        Returns:
            Log confirmation
        """
        experiment = {
            "id": params.get("experiment_id", f"exp_{int(time.time())}"),
            "model": params.get("model_name", "unknown"),
            "dataset": params.get("dataset", ""),
            "epochs": params.get("epochs", 0),
            "batch_size": params.get("batch_size", 0),
            "results": params.get("results", {}),
            "metrics": params.get("metrics", {}),
            "notes": params.get("notes", ""),
            "timestamp": time.time(),
        }

        self._experiment_log.append(experiment)

        return {
            "status": "logged",
            "experiment_id": experiment["id"],
            "total_experiments": len(self._experiment_log),
            "experiment": experiment,
        }

    def _estimate_hardware(
        self,
        model_name: str,
        category: str,
        epochs: int,
        batch_size: int,
    ) -> dict:
        """
        Estimate hardware requirements for training.

        Args:
            model_name: Model name
            category: Subnet category
            epochs: Number of epochs
            batch_size: Batch size

        Returns:
            Hardware estimate dictionary
        """
        # Base estimates by model size
        model_vram: dict[str, float] = {
            "small": 4,       # < 100M parameters
            "medium": 8,      # 100M - 1B parameters
            "large": 16,      # 1B - 7B parameters
            "xlarge": 40,     # 7B+ parameters
        }

        # Detect model size from name (heuristic)
        model_lower = model_name.lower()
        if any(x in model_lower for x in ["7b", "8b", "13b", "llama", "mistral"]):
            size = "xlarge"
        elif any(x in model_lower for x in ["large", "1b", "bert-large"]):
            size = "large"
        elif any(x in model_lower for x in ["base", "distil", "small"]):
            size = "small"
        else:
            size = "medium"

        base_vram = model_vram.get(size, 8)

        # Adjust for batch size
        batch_multiplier = batch_size / 8
        estimated_vram = base_vram * batch_multiplier * 1.5  # 1.5x for optimizer states

        # Adjust for category
        category_multiplier: dict[str, float] = {
            "multimodal": 1.5,
            "vision": 1.3,
            "audio": 1.2,
            "nlp": 1.0,
            "inference": 1.0,
            "data": 0.5,
            "compute": 0.5,
        }
        estimated_vram *= category_multiplier.get(category, 1.0)

        # Estimate RAM (typically 2x VRAM)
        estimated_ram = estimated_vram * 2

        # Estimate time (very rough)
        time_per_epoch: dict[str, float] = {
            "small": 0.5,
            "medium": 2,
            "large": 4,
            "xlarge": 8,
        }
        estimated_hours = time_per_epoch.get(size, 2) * epochs

        # Disk for checkpoints
        checkpoint_size_gb = base_vram * 0.25 * epochs  # ~0.25 GB per checkpoint per epoch size

        return {
            "estimated_gpu_vram_gb": round(estimated_vram, 1),
            "estimated_ram_gb": round(estimated_ram, 1),
            "estimated_cpu_cores": 4,
            "estimated_disk_gb": round(checkpoint_size_gb + 10, 1),  # +10 for dataset
            "estimated_time_hours": round(estimated_hours, 1),
            "model_size_category": size,
            "batch_size": batch_size,
            "epochs": epochs,
        }

    def _check_hardware_compatibility(self, estimate: dict) -> dict:
        """Check if available hardware meets estimate."""
        if not self._hardware_profile:
            return {"compatible": False, "reason": "No hardware profile available"}

        issues: list[str] = []
        has_gpu = self._hardware_profile.get("has_gpu", False)
        vram = self._hardware_profile.get("vram_gb", 0)
        ram = self._hardware_profile.get("ram_gb", 0)

        if not has_gpu:
            issues.append("No GPU available - training will be very slow")

        if has_gpu and vram < estimate["estimated_gpu_vram_gb"]:
            issues.append(
                f"Insufficient VRAM: {vram}GB < {estimate['estimated_gpu_vram_gb']}GB needed"
            )

        if ram < estimate["estimated_ram_gb"]:
            issues.append(
                f"Insufficient RAM: {ram}GB < {estimate['estimated_ram_gb']}GB needed"
            )

        return {
            "compatible": len(issues) == 0,
            "issues": issues,
            "available": {
                "vram_gb": vram,
                "ram_gb": ram,
            },
            "required": {
                "vram_gb": estimate["estimated_gpu_vram_gb"],
                "ram_gb": estimate["estimated_ram_gb"],
            },
        }

    def _get_hyperparameters(self, category: str) -> dict:
        """Get recommended hyperparameters for a category."""
        defaults: dict[str, dict] = {
            "nlp": {
                "learning_rate": 2e-5,
                "weight_decay": 0.01,
                "warmup_steps": 500,
                "max_seq_length": 512,
                "optimizer": "AdamW",
                "scheduler": "linear",
            },
            "vision": {
                "learning_rate": 1e-4,
                "weight_decay": 0.001,
                "warmup_steps": 200,
                "image_size": 224,
                "optimizer": "Adam",
                "scheduler": "cosine",
            },
            "audio": {
                "learning_rate": 5e-5,
                "weight_decay": 0.01,
                "warmup_steps": 300,
                "sample_rate": 16000,
                "optimizer": "AdamW",
                "scheduler": "linear",
            },
            "multimodal": {
                "learning_rate": 1e-5,
                "weight_decay": 0.01,
                "warmup_steps": 1000,
                "optimizer": "AdamW",
                "scheduler": "cosine",
            },
            "default": {
                "learning_rate": 1e-4,
                "weight_decay": 0.01,
                "warmup_steps": 100,
                "optimizer": "AdamW",
                "scheduler": "linear",
            },
        }
        return defaults.get(category, defaults["default"])
