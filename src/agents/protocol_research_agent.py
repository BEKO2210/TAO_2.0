"""
Protocol Research Agent (Agent 2).

Researches the Bittensor protocol and provides comprehensive
explanations of subnets, miners, validators, Yuma Consensus,
stake mechanisms, emissions, and key concepts.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "protocol_research_agent"
AGENT_VERSION: str = "1.0.0"


class ProtocolResearchAgent:
    """
    Agent for Bittensor protocol research and documentation.

    Provides structured knowledge about the Bittensor protocol including
    subnets, miners, validators, Yuma Consensus, stake mechanisms,
    emissions, and key terminology. Serves as the knowledge base for
    the entire swarm.
    """

    # Bittensor protocol knowledge base
    _PROTOCOL_KNOWLEDGE: dict[str, Any] = {
        "overview": {
            "name": "Bittensor",
            "token": "TAO",
            "type": "Decentralized AI Network",
            "consensus": "Yuma Consensus",
            "launched": "2021",
            "description": (
                "Bittensor is a decentralized machine learning network "
                "where nodes (miners) compete to provide the best AI models "
                "and services, validated by validator nodes. The network "
                "uses the TAO token for incentives and governance."
            ),
        },
        "subnets": {
            "description": (
                "Subnets are specialized sub-networks within Bittensor, "
                "each focused on a specific AI task or domain. Each subnet "
                "has its own miners, validators, and incentive mechanism."
            ),
            "key_concepts": [
                "NetUID: Unique identifier for each subnet",
                "Subnet 0: Root network (governance)",
                "Registration: Requires burning TAO to register a neuron",
                "Recycling: Registration cost is recycled to the network",
                "Immunity Period: Time before a new neuron can be deregistered",
                "Tempo: Block interval for subnet operations (~360 blocks)",
            ],
            "parameters": [
                "alpha_stakes: Stake distribution in the subnet",
                "difficulty: Registration difficulty ( adjusts dynamically)",
                "max_allowed_uids: Maximum neurons in the subnet",
                "min_allowed_weights: Minimum weights validators must set",
                "max_weight_limit: Maximum weight a validator can assign",
                "tempo: Blocks between subnet epochs",
            ],
        },
        "miners": {
            "description": (
                "Miners are nodes that provide AI services or computations "
                "within a subnet. They compete based on the quality of their "
                "outputs as evaluated by validators."
            ),
            "requirements": [
                "Registered neuron on the target subnet",
                "Sufficient hardware for the subnet's task",
                "Running server/serving axon for requests",
                "Stake (self-stake or delegated) for incentive eligibility",
            ],
            "incentive_mechanism": (
                "Miners receive emissions proportional to their performance "
                "scores from validators. Higher quality outputs = higher rewards."
            ),
        },
        "validators": {
            "description": (
                "Validators evaluate miner outputs and set weights that "
                "determine the emission distribution. They require significant "
                "stake to be in the top validator set (typically 64 per subnet)."
            ),
            "requirements": [
                "Large TAO stake (self or delegated)",
                "Reliable hardware (24/7 uptime)",
                "Accurate evaluation logic for the subnet",
                "Regular weight-setting operations",
            ],
            "responsibilities": [
                "Query miners and evaluate responses",
                "Set weights reflecting miner quality",
                "Run axon for communication",
                "Maintain uptime and sync with the network",
            ],
        },
        "yuma_consensus": {
            "description": (
                "Yuma Consensus is Bittensor's consensus mechanism that "
                "determines how emissions are distributed. Validators set "
                "weights on miners, and the consensus algorithm combines "
                "these weights with stake to calculate final rewards."
            ),
            "mechanism": [
                "1. Validators evaluate miners and assign weights W[i][j]",
                "2. Weights are normalized per validator",
                "3. Consensus weights are computed using validator stake",
                "4. Emissions = f(consensus_weights, stake)",
                "5. Trust and rank scores are computed per miner",
            ],
            "key_metrics": [
                "Trust: How much validators agree on a miner",
                "Rank: Miner's relative performance score",
                "Consensus: Weighted agreement across validators",
                "Incentive: Final reward score for the miner",
                "Dividend: Rewards validators receive for good evaluation",
                "Emission: Actual TAO emitted to the neuron",
            ],
        },
        "stake": {
            "description": (
                "Staking is the process of locking TAO tokens to a "
                "hotkey to participate in the network. Staked tokens "
                "earn emissions but are subject to slashing risks."
            ),
            "concepts": [
                "Coldkey: Owner key that holds funds and stake",
                "Hotkey: Operational key used for mining/validating",
                "Self-Stake: Stake from coldkey to own hotkey",
                "Delegated Stake: Others stake to your hotkey",
                "Unstaking: Removes stake back to coldkey (with delay)",
                "Slashing: Penalty for malicious behavior (currently minimal)",
            ],
        },
        "emissions": {
            "description": (
                "Emissions are the TAO rewards distributed to neurons. "
                "1 TAO is emitted approximately every 12 seconds. "
                "The distribution follows the Yuma Consensus weights."
            ),
            "mechanics": [
                "Block time: ~12 seconds",
                "TAO per block: 1 TAO",
                "Halving schedule: Every ~10.5 million blocks (~4 years)",
                "Subnet allocation: Each subnet gets a portion of emissions",
                "Neuron allocation: Based on incentive scores within subnet",
            ],
        },
        "keys": {
            "description": (
                "Bittensor uses a hierarchical key system for security "
                "and operational separation."
            ),
            "coldkey": (
                "The coldkey is the main owner key. It holds TAO balance, "
                "controls stake, and is used for high-value operations. "
                "It should be kept secure and offline when possible."
            ),
            "hotkey": (
                "The hotkey is the operational key used for day-to-day "
                "mining and validation. It has limited permissions and "
                "does not directly hold funds."
            ),
            "security_notes": [
                "NEVER share coldkey seed phrase",
                "Hotkeys can be rotated without losing stake",
                "Coldkey protects all stake - keep it secure",
                "Use separate hotkeys for different subnets",
            ],
        },
        "risks": {
            "network_risks": [
                "Subnet deregistration if underperforming",
                "Validator dropping from top set",
                "Emission volatility based on competition",
                "Network upgrades requiring client updates",
            ],
            "financial_risks": [
                "TAO price volatility",
                "Registration cost (burn) is non-refundable",
                "Stake lock-up period during unstaking",
                "Potential for slashing (future risk)",
            ],
            "operational_risks": [
                "Hardware failure during critical periods",
                "Software bugs causing downtime",
                "Network connectivity issues",
                "Client compatibility after updates",
            ],
        },
    }

    def __init__(self, config: dict) -> None:
        """
        Initialize the ProtocolResearchAgent.

        Args:
            config: Configuration dictionary
        """
        self.config: dict = config
        self._status: str = "idle"
        self._research_log: list[dict] = []
        logger.info(
            "ProtocolResearchAgent initialized (knowledge entries=%d)",
            len(self._PROTOCOL_KNOWLEDGE),
        )

    def run(self, task: dict) -> dict:
        """
        Run protocol research.

        Args:
            task: Dictionary with optional 'params' containing:
                - topic: Specific topic to research (e.g. "subnets", "staking")
                - query: Free-form query string

        Returns:
            Research results with protocol notes, explanations, and risks
        """
        self._status = "running"
        params = task.get("params", {})
        topic = params.get("topic", "")
        query = params.get("query", "")

        logger.info("ProtocolResearchAgent: researching topic=%s", topic or query or "full")

        try:
            notes = self._get_protocol_notes(topic, query)
            glossary = self._get_term_explanations(query)
            risks = self._get_risk_assessment(topic)

            result = {
                "protocol_notes": notes,
                "term_explanations": glossary,
                "risks": risks,
                "topics_available": list(self._PROTOCOL_KNOWLEDGE.keys()),
            }

            self._research_log.append({
                "timestamp": time.time(),
                "topic": topic,
                "query": query,
            })
            self._status = "complete"
            logger.info("ProtocolResearchAgent: research complete")
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("ProtocolResearchAgent: research failed: %s", e)
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
            "research_count": len(self._research_log),
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
        return True, ""

    def _get_protocol_notes(self, topic: str, query: str) -> dict:
        """
        Get protocol notes for a topic or query.

        Args:
            topic: Specific topic key
            query: Free-form query

        Returns:
            Protocol notes dictionary
        """
        topic_lower = topic.lower()

        # Direct topic lookup
        if topic_lower and topic_lower in self._PROTOCOL_KNOWLEDGE:
            return {topic_lower: self._PROTOCOL_KNOWLEDGE[topic_lower]}

        # Search across all topics for query match
        if query:
            query_lower = query.lower()
            matches: dict[str, Any] = {}
            for key, value in self._PROTOCOL_KNOWLEDGE.items():
                value_str = str(value).lower()
                if query_lower in key or query_lower in value_str:
                    matches[key] = value
            if matches:
                return matches

        # Return all knowledge if no specific match
        return dict(self._PROTOCOL_KNOWLEDGE)

    def _get_term_explanations(self, query: str) -> dict:
        """
        Get explanations for key Bittensor terms.

        Args:
            query: Optional search query

        Returns:
            Dictionary of term -> explanation
        """
        terms: dict[str, str] = {
            "TAO": "The native token of Bittensor. Used for staking, governance, and incentives.",
            "Subnet": "A specialized sub-network with its own miners, validators, and task.",
            "NetUID": "Unique numeric identifier for a subnet (e.g., 1, 11, 18).",
            "Miner": "A node that provides AI services/computations in a subnet.",
            "Validator": "A node that evaluates miner quality and sets weights.",
            "Neuron": "A registered entity (miner or validator) on the Bittensor network.",
            "Coldkey": "The main owner key that holds TAO and controls stake.",
            "Hotkey": "The operational key used for mining/validating.",
            "Stake": "TAO tokens locked to a hotkey for network participation.",
            "Emission": "TAO rewards distributed to neurons based on performance.",
            "Yuma Consensus": "Bittensor's consensus mechanism for reward distribution.",
            "Trust": "Metric of how much validators agree on a miner's quality.",
            "Rank": "Relative performance score of a miner in a subnet.",
            "Dividend": "Rewards validators earn for accurate evaluations.",
            "Incentive": "The reward score that determines a miner's emission.",
            "Tempo": "Block interval for subnet epoch operations (~360 blocks).",
            "Recycling": "Registration cost is burned/recycled to the network.",
            "Immunity Period": "Time a new neuron is protected from deregistration.",
            "Root Network": "Subnet 0, the governance subnet.",
            "Axon": "Server endpoint that receives and responds to network requests.",
            "Dendrite": "Client that queries miner axons.",
            "Subtensor": "The Bittensor blockchain node connection.",
            "Metagraph": "Network state containing all neuron information for a subnet.",
            "Burn": "TAO destroyed during registration (cost varies by demand).",
            "Delegate": "Allow others to stake TAO to your hotkey.",
            "Slashing": "Penalty for malicious behavior (future risk).",
            "Halving": "Emission reduction by 50% every ~4 years.",
        }

        if query:
            query_lower = query.lower()
            return {
                k: v for k, v in terms.items()
                if query_lower in k.lower() or query_lower in v.lower()
            }

        return terms

    def _get_risk_assessment(self, topic: str) -> dict:
        """
        Get risk assessment for a topic.

        Args:
            topic: Topic to assess risks for

        Returns:
            Risk assessment dictionary
        """
        risks = self._PROTOCOL_KNOWLEDGE.get("risks", {})

        if not topic:
            return risks

        topic_lower = topic.lower()
        filtered: dict[str, Any] = {}

        for category, items in risks.items():
            category_str = str(category).lower()
            items_str = str(items).lower()
            if topic_lower in category_str or topic_lower in items_str:
                filtered[category] = items

        return filtered if filtered else risks
