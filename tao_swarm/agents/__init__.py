"""
Agents module for TAO/Bittensor Multi-Agent System.

Exports all 15 specialized agents of the swarm:
1. System Check Agent
2. Protocol Research Agent
3. Subnet Discovery Agent
4. Subnet Scoring Agent
5. Wallet Watch Agent
6. Market & Trade Agent
7. Risk & Security Agent
8. Miner Engineering Agent
9. Validator Engineering Agent
10. Training & Experiment Agent
11. Infrastructure & DevOps Agent
12. Dashboard Design Agent
13. Full-Stack Development Agent
14. QA & Test Agent
15. Documentation Agent
"""

from tao_swarm.agents.dashboard_design_agent import AGENT_NAME as DASHBOARD_DESIGN_NAME
from tao_swarm.agents.dashboard_design_agent import DashboardDesignAgent
from tao_swarm.agents.documentation_agent import AGENT_NAME as DOCUMENTATION_NAME
from tao_swarm.agents.documentation_agent import DocumentationAgent
from tao_swarm.agents.fullstack_dev_agent import AGENT_NAME as FULLSTACK_DEV_NAME
from tao_swarm.agents.fullstack_dev_agent import FullstackDevAgent
from tao_swarm.agents.infra_devops_agent import AGENT_NAME as INFRA_DEVOPS_NAME
from tao_swarm.agents.infra_devops_agent import InfraDevopsAgent
from tao_swarm.agents.market_trade_agent import AGENT_NAME as MARKET_TRADE_NAME
from tao_swarm.agents.market_trade_agent import MarketTradeAgent
from tao_swarm.agents.miner_engineering_agent import AGENT_NAME as MINER_ENGINEERING_NAME
from tao_swarm.agents.miner_engineering_agent import MinerEngineeringAgent
from tao_swarm.agents.protocol_research_agent import AGENT_NAME as PROTOCOL_RESEARCH_NAME
from tao_swarm.agents.protocol_research_agent import ProtocolResearchAgent
from tao_swarm.agents.qa_test_agent import AGENT_NAME as QA_TEST_NAME
from tao_swarm.agents.qa_test_agent import QATestAgent
from tao_swarm.agents.risk_security_agent import AGENT_NAME as RISK_SECURITY_NAME
from tao_swarm.agents.risk_security_agent import RiskSecurityAgent
from tao_swarm.agents.subnet_discovery_agent import AGENT_NAME as SUBNET_DISCOVERY_NAME
from tao_swarm.agents.subnet_discovery_agent import SubnetDiscoveryAgent
from tao_swarm.agents.subnet_scoring_agent import AGENT_NAME as SUBNET_SCORING_NAME
from tao_swarm.agents.subnet_scoring_agent import SubnetScoringAgent
from tao_swarm.agents.system_check_agent import AGENT_NAME as SYSTEM_CHECK_NAME
from tao_swarm.agents.system_check_agent import SystemCheckAgent
from tao_swarm.agents.training_experiment_agent import AGENT_NAME as TRAINING_EXPERIMENT_NAME
from tao_swarm.agents.training_experiment_agent import TrainingExperimentAgent
from tao_swarm.agents.validator_engineering_agent import AGENT_NAME as VALIDATOR_ENGINEERING_NAME
from tao_swarm.agents.validator_engineering_agent import ValidatorEngineeringAgent
from tao_swarm.agents.wallet_watch_agent import AGENT_NAME as WALLET_WATCH_NAME
from tao_swarm.agents.wallet_watch_agent import WalletWatchAgent

__all__ = [
    "DashboardDesignAgent",
    "DocumentationAgent",
    "FullstackDevAgent",
    "InfraDevopsAgent",
    "MarketTradeAgent",
    "MinerEngineeringAgent",
    "ProtocolResearchAgent",
    "QATestAgent",
    "RiskSecurityAgent",
    "SubnetDiscoveryAgent",
    "SubnetScoringAgent",
    "SystemCheckAgent",
    "TrainingExperimentAgent",
    "ValidatorEngineeringAgent",
    "WalletWatchAgent",
]

# AGENT_NAME constants for easy reference
AGENT_NAMES: list[str] = [
    SYSTEM_CHECK_NAME,
    PROTOCOL_RESEARCH_NAME,
    SUBNET_DISCOVERY_NAME,
    SUBNET_SCORING_NAME,
    WALLET_WATCH_NAME,
    MARKET_TRADE_NAME,
    RISK_SECURITY_NAME,
    MINER_ENGINEERING_NAME,
    VALIDATOR_ENGINEERING_NAME,
    TRAINING_EXPERIMENT_NAME,
    INFRA_DEVOPS_NAME,
    DASHBOARD_DESIGN_NAME,
    FULLSTACK_DEV_NAME,
    QA_TEST_NAME,
    DOCUMENTATION_NAME,
]
